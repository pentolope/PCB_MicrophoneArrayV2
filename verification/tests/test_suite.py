"""Rev A expectation, portability, source-hygiene and mutation tests."""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from pcbqa import core                              # noqa: E402
from pcbqa.core import Context, Manifest, Status     # noqa: E402
from pcbqa.gates import (g_provenance, g_checks, g_geometry,  # noqa: F401
                         g_contracts, g_assembly, g_export_parity)   # noqa: E402,F401
from tests import build_portability                 # noqa: E402

REVA = os.path.join(HERE, "boards", "reva.json")
EXPECTED = os.path.join(HERE, "boards", "reva.expected.json")
PORTABILITY = os.path.join(HERE, "boards", "portability.json")
PYTHON = sys.executable


def run_validator(manifest, extra=()):
    proc = subprocess.run([PYTHON, os.path.join(HERE, "run.py"), "validate", manifest,
                           *extra], capture_output=True, text=True, cwd=HERE)
    return proc


def _remove(path):
    """Cleanup that tolerates a file another step already removed."""
    try:
        os.unlink(path)
    except (FileNotFoundError, PermissionError):
        pass


def _write_json(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return path


def validate(manifest_path):
    """Run gates in-process and return {gate_id: result_dict}."""
    manifest = Manifest(manifest_path)
    workdir = tempfile.mkdtemp(prefix="pcbqa_")
    ctx = Context(manifest, workdir)
    results = core.run_all(ctx)
    return {r.gate_id: r.to_dict() for r in results}, ctx


# ---------------------------------------------------------------------------
# Rev A must be rejected, gate by gate
# ---------------------------------------------------------------------------

class RevAExpectedFailureMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = json.load(open(EXPECTED, encoding="utf-8"))
        cls.results, _ctx = validate(REVA)

    def test_every_gate_has_an_expectation(self):
        missing = sorted(set(self.results) - set(self.expected["gates"]))
        self.assertFalse(missing, f"gates without a recorded expectation: {missing}")

    def test_gate_statuses_match_expectation(self):
        wrong = []
        for gate_id, want in self.expected["gates"].items():
            got = self.results.get(gate_id, {}).get("status")
            if got != want:
                wrong.append(f"{gate_id}: expected {want}, observed {got}")
        self.assertFalse(wrong, "\n".join(wrong))

    def test_verdict_is_rejected(self):
        blocking = [g for g, r in self.results.items()
                    if r["status"] in Status.BLOCKING]
        self.assertTrue(blocking, "Rev A must be rejected by at least one gate")

    def test_anchor_counts_reproduce_independently(self):
        wrong = []
        for path, want in self.expected["anchors"].items():
            gate_id, key = path.rsplit(".", 1)
            got = self.results[gate_id]["measurements"].get(key)
            if got != want:
                wrong.append(f"{path}: anchor {want}, recalculated {got}")
        self.assertFalse(wrong, "\n".join(wrong))

    def test_cli_exit_status_is_nonzero(self):
        proc = run_validator(REVA)
        self.assertNotEqual(proc.returncode, 0,
                            "validator must exit nonzero on Rev A")

    def test_all_gates_run_after_the_first_failure(self):
        registered = {e["id"] for e in core.registered()}
        self.assertEqual(set(self.results), registered,
                         "validation stopped early; every gate must report")


# ---------------------------------------------------------------------------
# release must be blocked and must not seal anything
# ---------------------------------------------------------------------------

class ReleaseBlocked(unittest.TestCase):
    def test_release_creates_no_sealed_package(self):
        proc = subprocess.run([PYTHON, os.path.join(HERE, "run.py"), "release", REVA],
                              capture_output=True, text=True, cwd=HERE)
        self.assertNotEqual(proc.returncode, 0)
        out = os.path.join(HERE, "out", "microphone_array_v2-revA")
        for forbidden in ("release_sealed", "release_candidate_UNSEALED"):
            self.assertFalse(os.path.isdir(os.path.join(out, forbidden)),
                             f"{forbidden} was created despite failures")
        unsafe = os.path.join(out, "release_UNSAFE_diagnostic")
        self.assertTrue(os.path.isdir(unsafe))
        self.assertTrue(os.path.isfile(os.path.join(unsafe, "DO_NOT_ORDER.txt")))
        # No orderable archive in anything the release itself produced. The
        # clean source copy is excluded: it is an input, not an output.
        for root, dirs, files in os.walk(out):
            dirs[:] = [d for d in dirs if d != "clean_project"]
            for name in files:
                self.assertFalse(name.lower().endswith(".zip"),
                                 f"release produced an orderable archive: {name}")

    def test_missing_mandatory_gate_blocks_release(self):
        """A gate that is NOT_APPLICABLE but mandatory must block sealing."""
        doc = json.load(open(REVA, encoding="utf-8"))
        doc.pop("via_mask")                      # makes four VIA gates N/A
        tmp = _write_json(os.path.join(HERE, "boards", "_tmp_mandatory.json"), doc)
        self.addCleanup(_remove, tmp)
        proc = subprocess.run([PYTHON, os.path.join(HERE, "run.py"), "release", tmp],
                              capture_output=True, text=True, cwd=HERE)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("NOT_APPLICABLE", proc.stdout)

    def test_release_profile_with_no_mandatory_gates_is_refused(self):
        doc = json.load(open(REVA, encoding="utf-8"))
        doc["release_profile"]["mandatory_gates"] = []
        tmp = _write_json(os.path.join(HERE, "boards", "_tmp_empty_profile.json"), doc)
        self.addCleanup(_remove, tmp)
        proc = subprocess.run([PYTHON, os.path.join(HERE, "run.py"), "release", tmp],
                              capture_output=True, text=True, cwd=HERE)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("names no mandatory gates", proc.stdout)


# ---------------------------------------------------------------------------
# portability
# ---------------------------------------------------------------------------

class Portability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_portability.build()
        cls.results, _ctx = validate(PORTABILITY)

    def test_generic_gates_run_on_a_structurally_different_board(self):
        for gate_id in ("STACK.NATIVE_VS_MANIFEST", "VIA.MASK_CLEARANCE_TARGET",
                        "VIA.MASK_CLEARANCE_PROCESS", "VIA.ANNULUS_MASK_OVERLAP",
                        "VIA.IN_PAD_CONTACT", "ROUTE.ANGLE_STYLE",
                        "ROUTE.TINY_SEGMENTS", "ROUTE.GEOMETRY_HYGIENE"):
            status = self.results[gate_id]["status"]
            self.assertEqual(status, Status.PASS,
                             f"{gate_id} = {status}: "
                             f"{self.results[gate_id]['reason']}")

    def test_board_is_structurally_unlike_reva(self):
        stack = self.results["STACK.NATIVE_VS_MANIFEST"]["measurements"]
        self.assertEqual(stack["copper_layers"], 2)

    def test_absent_policy_is_not_applicable_not_silently_passing(self):
        for gate_id in ("CONTRACT.CONNECTOR", "NET.TOPOLOGY", "ARCH.CONTENTS",
                        "ARCH.PROVENANCE", "PROV.FIXTURE_INTEGRITY",
                        "PROV.REPORT_FRESHNESS", "BOM.NATIVE_PARITY",
                        "CONTRACT.PLACEMENT", "ERC.AUTHORITATIVE",
                        "DRC.AUTHORITATIVE"):
            result = self.results[gate_id]
            self.assertEqual(result["status"], Status.NOT_APPLICABLE, gate_id)
            self.assertTrue(result["reason"], f"{gate_id} gave no reason")

    def test_cli_accepts_the_other_board(self):
        proc = run_validator(PORTABILITY)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:])


# ---------------------------------------------------------------------------
# no board-specific identifiers in generic checker source
# ---------------------------------------------------------------------------

class GenericSourceHygiene(unittest.TestCase):
    """Board identity must live in configuration, never in the framework."""

    PACKAGE = os.path.join(HERE, "pcbqa")

    def _sources(self):
        for base, _dirs, files in os.walk(self.PACKAGE):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(base, name)
                    yield path, open(path, encoding="utf-8").read()

    def _framework_vocabulary(self):
        """Words the framework itself owns: statuses and gate-ID components."""
        # Framework statuses, gate-ID components, and industry vocabulary that
        # belongs to the domain rather than to any board.
        vocab = {Status.PASS, Status.FAIL, Status.ERROR, Status.NOT_APPLICABLE,
                 "REJECTED", "ACCEPTED",
                 "BOM", "CPL", "ERC", "DRC", "PTH", "NPTH", "SMD", "THT",
                 "PCB", "JSON", "CSV", "UTC", "URL", "ID", "IU", "MM"}
        for entry in core.registered():
            vocab.update(re.split(r"[._]", entry["id"]))
        return vocab

    def _identifiers_from_configs(self):
        """Board-specific tokens taken from real board manifests only.

        The expectation file is not a manifest and is excluded: it legitimately
        contains gate IDs and status words, which belong to the framework.
        """
        tokens = set()
        for name in os.listdir(os.path.join(HERE, "boards")):
            if not name.endswith(".json"):
                continue
            doc = json.load(open(os.path.join(HERE, "boards", name), encoding="utf-8"))
            if "schema_version" not in doc:
                continue

            def walk(node):
                if isinstance(node, dict):
                    for k, v in node.items():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
                elif isinstance(node, str):
                    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_+.]{2,}", node):
                        tokens.add(word)
            walk(doc)
        generic = {
            "signal", "plane", "front", "back", "female", "male", "socket",
            "header", "true", "false", "null", "SMD", "designator", "Designator",
            "Layer", "Rotation", "json", "csv", "zip", "gerbers", "generated",
            "microphone_array_v2", "widget_b", "kicad_cli", "Program", "Files",
            "KiCad", "bin", "exe", "https", "jlcpcb", "com", "capabilities",
            "pcb", "sha256", "kicad", "command", "constraint", "native_kicad",
            "Copper", "Top", "Bot", "Inr", "Soldermask", "Legend", "Paste",
            "Profile", "Drill", "plated", "nonplated", "JobFile", "Drillmap",
            "annulus_to_opening_mm", "pinsocket", "receptacle", "pinheader",
            "plug", "radial", "README", "docs", "constraints", "tools",
            "check_routes", "netlist", "make_release", "widget", "cpl", "bom",
            "MANIFEST", "HASHES", "project", "fixtures", "reva", "portability",
        }
        generic |= self._framework_vocabulary()
        return {t for t in tokens if t not in generic}

    def test_no_board_identifier_appears_in_framework_source(self):
        board_tokens = self._identifiers_from_configs()
        # Only look for tokens that are plausibly board identity, not English.
        suspicious = {t for t in board_tokens
                      if re.fullmatch(r"[A-Z][A-Z0-9_+]{2,}", t)
                      or re.fullmatch(r"[A-Z]{1,3}\d+", t)}
        offenders = []
        for path, text in self._sources():
            for token in suspicious:
                if re.search(rf"\b{re.escape(token)}\b", text):
                    offenders.append(f"{os.path.relpath(path, HERE)}: {token}")
        self.assertFalse(offenders,
                         "board-specific identifiers found in generic source:\n"
                         + "\n".join(sorted(offenders)))

    def test_no_expected_defect_counts_in_framework_source(self):
        """A generic checker must not encode this board's known answers."""
        anchors = json.load(open(EXPECTED, encoding="utf-8"))["anchors"]
        # Only distinctive counts. Small integers (0, 2, 3, 9, 11, 12) occur
        # naturally as slot counts and version numbers; flagging them would be
        # noise, not evidence that a board's answers were hard-coded.
        values = {v for v in anchors.values() if isinstance(v, int) and v >= 20}
        offenders = []
        for path, text in self._sources():
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value in values:
                    offenders.append(
                        f"{os.path.relpath(path, HERE)}:{node.lineno}: {node.value}")
        self.assertFalse(offenders,
                         "known Rev A counts embedded in generic source:\n"
                         + "\n".join(offenders))

    def test_framework_declares_no_absolute_project_paths(self):
        offenders = []
        for path, text in self._sources():
            for m in re.finditer(r"[A-Za-z]:\\\\|/Users/|/home/", text):
                offenders.append(f"{os.path.relpath(path, HERE)}: {m.group(0)}")
        self.assertFalse(offenders, "absolute paths in framework source: " + str(offenders))


# ---------------------------------------------------------------------------
# mutation tests - each deliberate defect must be detected
# ---------------------------------------------------------------------------

class Mutations(unittest.TestCase):
    """Each mutation injects a defect; the suite must notice."""

    @classmethod
    def setUpClass(cls):
        results, _ = validate(REVA)
        cls.baseline_contacts = (results["VIA.ANNULUS_MASK_OVERLAP"]
                                 ["measurements"]["annulus_contacts"])

    def _mutated_manifest(self, mutate):
        doc = json.load(open(REVA, encoding="utf-8"))
        mutate(doc)
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          dir=os.path.join(HERE, "boards"),
                                          encoding="utf-8")
        json.dump(doc, tmp, indent=2)
        tmp.close()
        self.addCleanup(_remove, tmp.name)
        return tmp.name

    def test_relaxing_a_checker_threshold_without_the_manifest_is_detected(self):
        """CFG.NO_RIVAL_THRESHOLDS must catch a divergent constant in a checker."""
        results, _ = validate(REVA)
        rival = results["CFG.NO_RIVAL_THRESHOLDS"]
        self.assertEqual(rival["status"], Status.FAIL)
        constants = {f["constant"] for f in rival["findings"]}
        self.assertIn("BRANCH_SKEW_LIMIT_MM", constants)

    def test_threshold_parity_detects_a_gate_that_invents_a_limit(self):
        """A gate citing a manifest key whose value differs must be caught."""
        from pcbqa.core import GateResult
        manifest = Manifest(REVA)
        ctx = Context(manifest, tempfile.mkdtemp(prefix="pcbqa_"))
        applied = ctx.cache("applied_limits", dict)
        applied["FAKE.limit"] = {
            "value": 999.0,
            "source": manifest.source_of("routing.min_segment_mm"),
        }
        res = GateResult("CFG.THRESHOLD_PARITY", "t")
        g_contracts.threshold_parity(ctx, res)
        self.assertEqual(res.status, Status.FAIL)

    def test_stale_drc_report_substitution_is_detected(self):
        """Swapping in a report that names a different source must be caught."""
        results, _ = validate(REVA)
        fresh = results["PROV.REPORT_FRESHNESS"]
        self.assertEqual(fresh["status"], Status.FAIL)
        issues = {f.get("issue", "") for f in fresh["findings"]}
        self.assertTrue(any("not a current design source" in i or "older than" in i
                            or "no source hash" in i for i in issues), issues)

    def test_altered_output_after_hash_recorded_is_detected(self):
        """Mutate a packaged file and the release manifest hash must mismatch."""
        src = os.path.join(HERE, "fixtures", "reva", "project", "generated", "release")
        work = tempfile.mkdtemp(prefix="pcbqa_alt_")
        shutil.copytree(src, os.path.join(work, "release"))
        target = os.path.join(work, "release", "bom.csv")
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("MUTATED,,,,\n")
        path = self._mutated_manifest(lambda d: d["archive"].update({
            "manifest": os.path.relpath(
                os.path.join(work, "release", "MANIFEST.md"),
                os.path.join(HERE, "fixtures", "reva", "project")).replace("\\", "/"),
        }))
        results, _ = validate(path)
        arch = results["ARCH.PROVENANCE"]
        self.assertEqual(arch["status"], Status.FAIL)
        self.assertTrue(any("recorded hash no longer matches" in f.get("issue", "")
                            for f in arch["findings"]),
                        arch["findings"])

    def test_drill_map_in_the_archive_is_detected(self):
        results, _ = validate(REVA)
        arch = results["ARCH.CONTENTS"]
        self.assertEqual(arch["status"], Status.FAIL)
        self.assertTrue(any(f.get("file_function") == "Drillmap"
                            for f in arch["findings"]), arch["findings"])

    def test_adding_a_new_disallowed_file_to_the_archive_is_detected(self):
        src = os.path.join(HERE, "fixtures", "reva", "project", "generated",
                           "release", "microphone_array_v2-revA-fabrication.zip")
        work = tempfile.mkdtemp(prefix="pcbqa_zip_")
        dst = os.path.join(work, "mutated.zip")
        shutil.copy2(src, dst)
        with zipfile.ZipFile(dst, "a") as zf:
            zf.writestr("stray_notes.txt", "not fabrication data")
        rel = os.path.relpath(dst, os.path.join(HERE, "fixtures", "reva", "project"))
        path = self._mutated_manifest(
            lambda d: d["archive"].update({"zip": rel.replace("\\", "/")}))
        results, _ = validate(path)
        entries = [f.get("entry") for f in results["ARCH.CONTENTS"]["findings"]]
        self.assertIn("stray_notes.txt", entries)

    def test_bypassing_a_validation_stage_is_detected(self):
        """Removing a gate's policy makes it NOT_APPLICABLE, and the expectation
        matrix then fails - a stage cannot be silently skipped."""
        path = self._mutated_manifest(lambda d: d.pop("via_mask"))
        results, _ = validate(path)
        for gate_id in ("VIA.MASK_CLEARANCE_TARGET", "VIA.IN_PAD_CONTACT"):
            self.assertEqual(results[gate_id]["status"], Status.NOT_APPLICABLE)
        expected = json.load(open(EXPECTED, encoding="utf-8"))["gates"]
        drift = [g for g in ("VIA.MASK_CLEARANCE_TARGET", "VIA.IN_PAD_CONTACT")
                 if results[g]["status"] != expected[g]]
        self.assertTrue(drift, "bypassing a stage was not visible in the matrix")

    def test_rotated_pad_via_overlap_mutation_is_detected(self):
        """Rotating a pad so a previously clear via now overlaps must be caught."""
        import pcbnew
        from tests import synth
        from pcbqa import geom
        board = synth.new_board()
        net = synth.add_net(board, "N1")
        fp, _pad = synth.add_pad_footprint(board, "P1", 100, 100,
                                           pcbnew.PAD_SHAPE_RECT, (2.0, 0.4),
                                           rotation_deg=0.0, net=net)
        d = 0.9 / (2 ** 0.5)
        synth.add_via(board, 100 + d, 100 - d, net=net)
        clear = geom.BoardGeometry(board)
        self.assertFalse(clear.via_mask_report(clear.vias[0], "front")
                         ["annulus_contacts_opening"])
        fp.SetOrientationDegrees(45.0)
        mutated = geom.BoardGeometry(board)
        self.assertTrue(mutated.via_mask_report(mutated.vias[0], "front")
                        ["annulus_contacts_opening"],
                        "rotated-pad overlap mutation was not detected")


    def _fixture_copy(self, tag):
        work = tempfile.mkdtemp(prefix="pcbqa_" + tag + "_")
        project = os.path.join(work, "project")
        shutil.copytree(os.path.join(HERE, "fixtures", "reva", "project"), project)
        return project

    def _manifest_for(self, project, tag):
        doc = json.load(open(REVA, encoding="utf-8"))
        doc["project_root"] = os.path.relpath(
            project, os.path.join(HERE, "boards")).replace(os.sep, "/")
        doc.pop("fixture", None)
        tmp = _write_json(os.path.join(HERE, "boards", "_tmp_" + tag + ".json"), doc)
        self.addCleanup(_remove, tmp)
        return tmp

    @staticmethod
    def _via_centres_inside(mask_path, via_points):
        from shapely.geometry import Point
        from pcbqa import gerber as gbr
        mask = gbr.GerberFile(mask_path)
        count = 0
        for x, y in via_points:
            point = Point(x, y)
            if any(shape.contains(point) for _c, _fx, _fy, shape in mask.flashes):
                count += 1
        return count, mask

    def test_moving_a_defect_between_vias_is_detected(self):
        """Per-object truth moves while every total stays the same.

        Two solder-mask apertures are swapped in the shipped Gerber: a circular
        one sitting on one via and a rounded-rectangle one sitting on another.
        The number of apertures, the aperture list and the number of via
        centres inside an opening are all unchanged - a totals comparison sees
        nothing - but each of those two vias now faces a different opening with
        a different clearance, so the per-object comparison must fail.
        """
        import pcbnew
        from pcbqa import geom, gerber as gbr

        project = self._fixture_copy("swap")
        mask_path = os.path.join(project, "generated", "release", "gerbers",
                                 "microphone_array_v2-F_Mask.gbr")
        board = pcbnew.LoadBoard(os.path.join(project,
                                              "microphone_array_v2.kicad_pcb"))
        survey = geom.BoardGeometry(board, contact_tolerance_mm=1e-6)
        via_points = [(v.x, -v.y) for v in survey.vias]

        before, mask = self._via_centres_inside(mask_path, via_points)
        from shapely.affinity import translate
        from shapely.geometry import Point

        # A via with generous clearance in the shipped export, and a mask
        # opening that contains no via centre at all.
        def nearest_gap(shape_list, x, y):
            annulus = Point(x, y).buffer(0.225, quad_segs=32)
            return min(annulus.distance(sh) for sh in shape_list)

        shapes = [f[3] for f in mask.flashes]
        roomy = None
        for x, y in via_points:
            if nearest_gap(shapes, x, y) > 1.0:
                roomy = (x, y)
                break
        self.assertIsNotNone(roomy, "no via with generous clearance to relocate onto")

        spare = None
        for index, (code, fx, fy, shape) in enumerate(mask.flashes):
            if any(shape.contains(Point(x, y)) for x, y in via_points):
                continue
            half = max(shape.bounds[2] - shape.bounds[0],
                       shape.bounds[3] - shape.bounds[1]) / 2.0
            if half < 0.45:                     # must not swallow the via centre
                spare = (index, fx, fy, shape, half)
                break
        self.assertIsNotNone(spare, "no relocatable opening found")
        index, fx, fy, shape, half = spare

        # Park it 0.5 mm from the via centre: close enough to destroy the
        # clearance, far enough that the via centre stays outside the opening,
        # so the count of centres-inside - the only thing a totals comparison
        # looked at - is untouched.
        tx, ty = roomy[0] + 0.5, roomy[1]
        trial = list(shapes)
        trial[index] = translate(shape, tx - fx, ty - fy)
        self.assertEqual(sum(1 for x, y in via_points
                             if any(sh.contains(Point(x, y)) for sh in trial)),
                         before, "relocation must not change centres-inside")

        text = open(mask_path, encoding="utf-8").read()
        tok_from = "X%dY%dD03*" % (round(fx * 1e6), round(fy * 1e6))
        tok_to = "X%dY%dD03*" % (round(tx * 1e6), round(ty * 1e6))
        self.assertEqual(text.count(tok_from), 1, tok_from)
        open(mask_path, "w", encoding="utf-8").write(
            text.replace(tok_from, tok_to, 1))

        after, _ = self._via_centres_inside(mask_path, via_points)
        self.assertEqual(before, after,
                         "the mutation was supposed to preserve the totals a "
                         "counting comparison would look at")

        results, _ = validate(self._manifest_for(project, "swap"))
        gate = results["VIA.NATIVE_GERBER_AGREEMENT"]
        self.assertEqual(gate["status"], Status.FAIL,
                         "per-object gate missed a defect that moved between vias")
        issues = {f.get("issue", "") for f in gate["findings"]}
        self.assertTrue(
            any("clearance disagrees" in i or "different object" in i
                or "disagrees" in i for i in issues), issues)

    def test_moving_a_via_without_re_exporting_is_detected(self):
        """A via moved in the board but not re-exported must fail object matching."""
        import pcbnew
        project = self._fixture_copy("vmove")
        board_path = os.path.join(project, "microphone_array_v2.kicad_pcb")
        board = pcbnew.LoadBoard(board_path)
        via = next(t for t in board.Tracks() if isinstance(t, pcbnew.PCB_VIA))
        pos = via.GetPosition()
        via.SetPosition(pcbnew.VECTOR2I(pos.x + pcbnew.FromMM(0.5), pos.y))
        board.Save(board_path)

        results, _ = validate(self._manifest_for(project, "vmove"))
        gate = results["VIA.NATIVE_GERBER_AGREEMENT"]
        self.assertEqual(gate["status"], Status.FAIL)
        self.assertTrue(any("no plated drill hit" in f.get("issue", "")
                            for f in gate["findings"]), gate["findings"])

    def test_editing_a_shipped_gerber_is_detected(self):
        """A copper layer changed after export must fail per-layer parity."""
        work = tempfile.mkdtemp(prefix="pcbqa_layer_")
        project = os.path.join(work, "project")
        shutil.copytree(os.path.join(HERE, "fixtures", "reva", "project"), project)
        target = os.path.join(project, "generated", "release", "gerbers",
                              "microphone_array_v2-F_Cu.gbr")
        text = open(target, encoding="utf-8").read()
        cut = text.replace("D03*", "D02*", 1)      # one flash becomes a move
        self.assertNotEqual(text, cut)
        open(target, "w", encoding="utf-8").write(cut)

        doc = json.load(open(REVA, encoding="utf-8"))
        doc["project_root"] = os.path.relpath(
            project, os.path.join(HERE, "boards")).replace("\\", "/")
        doc.pop("fixture", None)
        tmp = _write_json(os.path.join(HERE, "boards", "_tmp_layer.json"), doc)
        self.addCleanup(_remove, tmp)
        results, _ = validate(tmp)
        gate = results["STACK.GERBER_PARITY"]
        self.assertEqual(gate["status"], Status.FAIL,
                         "per-layer parity missed an edited copper layer")
        self.assertTrue(any("differs from a fresh export" in f.get("issue", "")
                            for f in gate["findings"]), gate["findings"])

    def test_gerber_parser_fails_closed_on_unknown_aperture(self):
        from pcbqa import gerber
        work = tempfile.mkdtemp(prefix="pcbqa_gbr_")
        path = os.path.join(work, "bad.gbr")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("%FSLAX46Y46*%\n%MOMM*%\n%ADD10WeirdShape,1.0*%\n"
                     "D10*\nX1000000Y1000000D03*\nM02*\n")
        with self.assertRaises(gerber.GerberError):
            gerber.GerberFile(path)


if __name__ == "__main__":
    unittest.main()
