"""ERC and DRC against a positive control, then one mutation at a time.

Rev A must be rejected, which makes it useless for proving that these gates can
pass. A gate wired to a board that always fails looks exactly like a gate that
always fails. So everything here starts from `fixtures/clean` - a 20 mm square
with an empty schematic and no disabled rules, which reports nothing at all -
and each test changes one thing.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pcbqa import core, reports                          # noqa: E402
from pcbqa.core import Context, Manifest, Status         # noqa: E402
from pcbqa.gates import g_checks                         # noqa: E402,F401

CLEAN = os.path.join(HERE, "boards", "clean.json")
FIXTURE = os.path.join(HERE, "fixtures", "clean", "project")

ERC_GATE = "ERC.AUTHORITATIVE"
DRC_GATE = "DRC.AUTHORITATIVE"


class _Copy:
    """A writable copy of the clean fixture plus a manifest naming it."""

    def __init__(self, tag, mutate=None):
        self.work = tempfile.mkdtemp(prefix="pcbqa_cl_" + tag + "_")
        self.project = os.path.join(self.work, "project")
        shutil.copytree(FIXTURE, self.project)
        self.sch = os.path.join(self.project, "clean.kicad_sch")
        self.pcb = os.path.join(self.project, "clean.kicad_pcb")
        self.pro = os.path.join(self.project, "clean.kicad_pro")
        doc = json.load(open(CLEAN, encoding="utf-8"))
        doc["project_root"] = self.project
        if mutate:
            mutate(doc, self.project)
        self.manifest_path = os.path.join(self.work, "manifest.json")
        with open(self.manifest_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)

    def run(self, only):
        manifest = Manifest(self.manifest_path)
        ctx = Context(manifest, os.path.join(self.work, "wd"))
        return {r.gate_id: r for r in core.run_all(ctx, only=only)}

    def close(self):
        shutil.rmtree(self.work, ignore_errors=True)


def _stub_cli(directory, name, body):
    """A stand-in for kicad-cli that misbehaves in one specific way."""
    path = os.path.join(directory, name + (".cmd" if os.name == "nt" else ".sh"))
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(body)
    if os.name != "nt":
        os.chmod(path, 0o755)
    return path


class _Base(unittest.TestCase):
    def _copy(self, tag, mutate=None):
        box = _Copy(tag, mutate)
        self.addCleanup(box.close)
        return box


# ---------------------------------------------------------------------------
# the positive control
# ---------------------------------------------------------------------------

class CleanFixturePasses(_Base):
    def test_erc_and_drc_both_pass_on_the_clean_fixture(self):
        box = self._copy("baseline")
        results = box.run({ERC_GATE, DRC_GATE})
        for gate_id in (ERC_GATE, DRC_GATE):
            result = results[gate_id]
            self.assertEqual(result.status, Status.PASS,
                             "{}: {} {}".format(gate_id, result.reason,
                                                result.findings[:4]))
            self.assertEqual(result.measurements["exit_status"], 0)
            self.assertEqual(result.measurements["report_meta"]["ignored_checks"],
                             [])
            self.assertEqual(result.measurements["counts"], {})

    def test_the_recorded_command_carries_every_required_option(self):
        box = self._copy("options")
        results = box.run({ERC_GATE, DRC_GATE})
        for gate_id, kind in ((ERC_GATE, "erc"), (DRC_GATE, "drc")):
            command = results[gate_id].measurements["command"]
            for option in g_checks.required_options(kind):
                self.assertIn(option, command.split(),
                              "{} ran without {}".format(gate_id, option))
        drc = results[DRC_GATE].measurements["command"].split()
        for option in ("--severity-exclusions", "--refill-zones", "--save-board",
                       "--schematic-parity", "--all-track-errors"):
            self.assertIn(option, drc)

    def test_save_board_never_touches_the_design_being_checked(self):
        """DRC writes the board it checks, so it is pointed at a copy."""
        box = self._copy("nowrite")
        before = open(box.pcb, "rb").read()
        result = box.run({DRC_GATE})[DRC_GATE]
        self.assertEqual(result.status, Status.PASS, result.reason)
        self.assertEqual(open(box.pcb, "rb").read(), before,
                         "the authoritative DRC modified the design it was "
                         "asked to check")
        self.assertIsNotNone(result.measurements["checked_copy_sha256"])

    def test_a_required_option_cannot_be_relaxed_by_a_manifest(self):
        """Extra flags are the board's; required options are the validator's."""
        def drop(doc, _project):
            doc["checks"]["drc"]["extra_flags"] = ["--severity-error"]
        box = self._copy("norelax", drop)
        command = box.run({DRC_GATE})[DRC_GATE].measurements["command"].split()
        for option in g_checks.required_options("drc"):
            self.assertIn(option, command)
        self.assertIn("--severity-error", command)


# ---------------------------------------------------------------------------
# clean to dirty
# ---------------------------------------------------------------------------

class RealMutations(_Base):
    def test_a_dangling_label_turns_erc_from_pass_to_fail(self):
        clean = self._copy("erc_before").run({ERC_GATE})[ERC_GATE]
        self.assertEqual(clean.status, Status.PASS, clean.reason)

        def add_label(_doc, project):
            path = os.path.join(project, "clean.kicad_sch")
            text = open(path, encoding="utf-8").read()
            label = ('\t(label "ORPHAN"\n\t\t(at 100 100 0)\n'
                     '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
                     '\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n'
                     '\t\t(uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")\n\t)\n')
            open(path, "w", encoding="utf-8").write(
                text.replace("\t(sheet_instances", label + "\t(sheet_instances"))
        dirty = self._copy("erc_after", add_label).run({ERC_GATE})[ERC_GATE]
        self.assertEqual(dirty.status, Status.FAIL,
                         "a label attached to nothing is an ERC error")
        self.assertEqual(dirty.measurements["exit_status"],
                         g_checks.VIOLATIONS_EXIT_CODE)
        rules = {f.get("rule") for f in dirty.findings}
        self.assertIn("label_dangling", rules, dirty.findings[:4])

    def test_a_track_over_the_board_edge_turns_drc_from_pass_to_fail(self):
        clean = self._copy("drc_before").run({DRC_GATE})[DRC_GATE]
        self.assertEqual(clean.status, Status.PASS, clean.reason)

        def add_track(_doc, project):
            import pcbnew
            path = os.path.join(project, "clean.kicad_pcb")
            board = pcbnew.LoadBoard(path)
            track = pcbnew.PCB_TRACK(board)
            track.SetLayer(pcbnew.F_Cu)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(110),
                                           pcbnew.FromMM(110)))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(125), pcbnew.FromMM(110)))
            track.SetWidth(pcbnew.FromMM(0.25))
            board.Add(track)
            board.Save(path)
        dirty = self._copy("drc_after", add_track).run({DRC_GATE})[DRC_GATE]
        self.assertEqual(dirty.status, Status.FAIL,
                         "copper crossing the board outline is a DRC error")
        self.assertEqual(dirty.measurements["exit_status"],
                         g_checks.VIOLATIONS_EXIT_CODE)
        rules = {f.get("rule") for f in dirty.findings}
        self.assertIn("copper_edge_clearance", rules, dirty.findings[:4])

    def test_an_ignored_check_turns_drc_from_pass_to_fail(self):
        def ignore_one(_doc, project):
            path = os.path.join(project, "clean.kicad_pro")
            pro = json.load(open(path, encoding="utf-8"))
            pro["board"]["design_settings"]["rule_severities"][
                "copper_edge_clearance"] = "ignore"
            json.dump(pro, open(path, "w", encoding="utf-8"), indent=2)
        dirty = self._copy("ignored", ignore_one).run({DRC_GATE})[DRC_GATE]
        self.assertEqual(dirty.status, Status.FAIL,
                         "a check that did not run is not a check that passed")
        self.assertTrue(any("ignored one or more checks" in f.get("issue", "")
                            for f in dirty.findings), dirty.findings)


# ---------------------------------------------------------------------------
# reports and tools that cannot be trusted
# ---------------------------------------------------------------------------

class UnusableInputsAreErrors(_Base):
    def _cli_that(self, tag, body):
        def mutate(doc, project):
            doc["tools"]["kicad_cli"] = _stub_cli(project, "stub_cli", body)
        return self._copy(tag, mutate)

    def test_a_garbage_report_is_an_error_not_a_pass(self):
        """A report the reader does not recognise is not an empty report."""
        # The gate invokes:
        #     pcb drc --format json -o <path> ...options... <source>
        # so the output path the stub must write to is the sixth argument.
        # Writing to the wrong one produces no report at all, and the gate
        # would then error for a different reason than the one under test.
        body = ("@echo off\r\n"
                "echo {\"nonsense\": true} > %6\r\n"
                "exit /b 0\r\n")
        box = self._cli_that("garbage", body)
        result = box.run({DRC_GATE})[DRC_GATE]
        self.assertEqual(result.status, Status.ERROR,
                         "an unreadable report must never be read as 'no "
                         "findings': {}".format(result.reason))
        self.assertIn("unsupported DRC report schema", result.reason,
                      "the report must actually have been written and then "
                      "rejected by schema validation; erroring because no "
                      "file appeared would pass even with validation removed: "
                      + result.reason)
        self.assertNotIn("counts", result.measurements)

    def test_a_report_that_is_not_json_at_all_is_an_error(self):
        body = ("@echo off\r\n"
                "echo this is not json > %6\r\n"
                "exit /b 0\r\n")
        box = self._cli_that("notjson", body)
        result = box.run({DRC_GATE})[DRC_GATE]
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("not readable JSON", result.reason)

    def test_an_unsupported_schema_marker_is_refused(self):
        doc = drc_report(schema="https://schemas.kicad.org/drc.v9.json")
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(doc)
        self.assertEqual(reports.parse_drc(drc_report())[0], [])

    def test_an_unsupported_kicad_major_version_is_refused(self):
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(drc_report(kicad_version="11.0.0"))
        # And a version string the schema's own pattern rejects.
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(drc_report(kicad_version="ten"))

    def test_a_missing_required_report_field_is_refused(self):
        for field in ("source", "date", "kicad_version", "violations",
                      "unconnected_items", "schematic_parity",
                      "coordinate_units", "included_severities",
                      "ignored_checks"):
            doc = drc_report()
            doc.pop(field)
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="missing {} was accepted".format(field)):
                reports.parse_drc(doc)

    def test_a_missing_required_violation_or_item_field_is_refused(self):
        for field in ("type", "description", "severity", "items"):
            doc = drc_report(violations=[_violation()])
            doc["violations"][0].pop(field)
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="violation without {} accepted".format(field)):
                reports.parse_drc(doc)
        for field in ("uuid", "description", "pos"):
            doc = drc_report(violations=[_violation()])
            doc["violations"][0]["items"][0].pop(field)
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="item without {} accepted".format(field)):
                reports.parse_drc(doc)
        for axis in ("x", "y"):
            doc = drc_report(violations=[_violation()])
            doc["violations"][0]["items"][0]["pos"].pop(axis)
            with self.assertRaises(reports.ReportSchemaError):
                reports.parse_drc(doc)

    def test_an_invalid_uuid_is_refused(self):
        for bad in ("not-a-uuid", "11111111-2222-3333-4444", "", 17,
                    "11111111222233334444555555555555"):
            doc = drc_report(violations=[_violation()])
            doc["violations"][0]["items"][0]["uuid"] = bad
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="uuid {!r} accepted".format(bad)):
                reports.parse_drc(doc)

    def test_an_invalid_severity_is_refused(self):
        for bad in ("catastrophic", "exclusion", "", None):
            doc = drc_report(violations=[_violation()])
            doc["violations"][0]["severity"] = bad
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="severity {!r} accepted".format(bad)):
                reports.parse_drc(doc)

    def test_invalid_coordinate_units_are_refused(self):
        for bad in ("metres", "MM", "", 1):
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="units {!r} accepted".format(bad)):
                reports.parse_drc(drc_report(coordinate_units=bad))

    def test_a_disallowed_extra_field_is_refused(self):
        """Both schemas declare additionalProperties: false."""
        doc = drc_report()
        doc["invented_by_someone"] = True
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(doc)

        doc = drc_report(violations=[_violation()])
        doc["violations"][0]["confidence"] = 0.9
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(doc)

        doc = drc_report(violations=[_violation()])
        doc["violations"][0]["items"][0]["layer"] = "F.Cu"
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(doc)

    def test_a_wrong_field_type_is_refused(self):
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(drc_report(violations={}))
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(drc_report(source=42))
        doc = drc_report(violations=[_violation()])
        doc["violations"][0]["items"][0]["pos"]["x"] = "12.5"
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(doc)

    def test_our_own_provenance_annotations_do_not_break_validation(self):
        """The release binds hashes into reports it generated; ours, not KiCad's."""
        doc = drc_report()
        doc["source_sha256"] = "a" * 64
        doc["source_closure_sha256"] = "b" * 64
        doc["source_closure"] = {"x.kicad_pcb": "c" * 64}
        self.assertEqual(reports.parse_drc(doc)[0], [])

    def test_an_invocation_failure_is_an_error_and_is_never_waived(self):
        box = self._cli_that(
            "crash", "@echo off\r\necho simulated crash 1>&2\r\nexit /b 3\r\n")
        results = box.run({ERC_GATE, DRC_GATE})
        for gate_id, result in results.items():
            self.assertEqual(result.status, Status.ERROR, gate_id)
            self.assertIn("invocation failed", result.reason)
            self.assertNotIn("waived", result.measurements)

    def test_a_waiver_cannot_rescue_a_failed_invocation(self):
        """Even a perfectly formed waiver is irrelevant to a tool that crashed."""
        def mutate(doc, project):
            doc["tools"]["kicad_cli"] = _stub_cli(
                project, "stub_cli", "@echo off\r\nexit /b 3\r\n")
            doc["waivers"] = [{
                "gate": DRC_GATE, "rule": "clearance", "category": "violations",
                "items": [{"description": "T1", "location_mm": [1.0, 2.0]},
                          {"description": "T2", "location_mm": [3.0, 4.0]}],
                "reason": "reviewed", "reviewed_by": "someone",
                "reviewed_utc": "2026-08-01T00:00:00",
                "approved_source_sha256": "a" * 64,
                "approved_rules_sha256": "b" * 64,
                "approved_command_sha256": "c" * 64,
                "approved_report_sha256": "d" * 64}]
        box = self._copy("waived_crash", mutate)
        result = box.run({DRC_GATE})[DRC_GATE]
        self.assertEqual(result.status, Status.ERROR)
        self.assertEqual(result.measurements.get("waived"), None)

    def test_a_missing_report_is_an_error_even_on_the_violations_exit_code(self):
        box = self._cli_that("noreport", "@echo off\r\nexit /b 5\r\n")
        result = box.run({DRC_GATE})[DRC_GATE]
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("produced no report", result.reason)



# ---------------------------------------------------------------------------
# synthetic reports, built to satisfy the official schema by default so that
# each test can break exactly one thing
# ---------------------------------------------------------------------------

UUID = "11111111-2222-3333-4444-555555555555"


def _violation(x=25.4, y=50.8, rule="clearance", severity="error",
               description="Clearance violation"):
    return {"type": rule, "description": description, "severity": severity,
            "items": [{"uuid": UUID, "description": "Track [Net] on F.Cu",
                       "pos": {"x": x, "y": y}}]}


def drc_report(**over):
    doc = {"$schema": "https://schemas.kicad.org/drc.v1.json",
           "source": "board.kicad_pcb",
           "date": "2026-08-04T12:00:00+00:00",
           "kicad_version": "10.0.5",
           "coordinate_units": "mm",
           "included_severities": ["error", "warning", "exclusion"],
           "ignored_checks": [],
           "violations": [], "unconnected_items": [], "schematic_parity": []}
    if "schema" in over:
        doc["$schema"] = over.pop("schema")
    doc.update(over)
    return doc


def erc_report(**over):
    doc = {"$schema": "https://schemas.kicad.org/erc.v1.json",
           "source": "sheet.kicad_sch",
           "date": "2026-08-04T12:00:00+00:00",
           "kicad_version": "10.0.5",
           "coordinate_units": "mm",
           "included_severities": ["error", "warning", "exclusion"],
           "ignored_checks": [],
           "sheets": [{"uuid_path": "/" + UUID, "path": "/", "violations": []}]}
    if "schema" in over:
        doc["$schema"] = over.pop("schema")
    doc.update(over)
    return doc


class CoordinatesAreCanonicalMillimetres(unittest.TestCase):
    """Nothing is stored, compared or waived in the units it arrived in."""

    def test_equivalent_reports_in_mm_in_and_mils_agree(self):
        one_inch = [
            reports.parse_drc(drc_report(
                coordinate_units="mm",
                violations=[_violation(x=25.4, y=50.8)]))[0][0],
            reports.parse_drc(drc_report(
                coordinate_units="in",
                violations=[_violation(x=1.0, y=2.0)]))[0][0],
            reports.parse_drc(drc_report(
                coordinate_units="mils",
                violations=[_violation(x=1000.0, y=2000.0)]))[0][0],
        ]
        for finding in one_inch:
            self.assertAlmostEqual(finding["x_mm"], 25.4, places=9)
            self.assertAlmostEqual(finding["y_mm"], 50.8, places=9)
        self.assertEqual({f["source_units"] for f in one_inch},
                         {"mm", "in", "mils"},
                         "the units read must still be recorded, just not used "
                         "as if they were millimetres")

    def test_an_inch_report_is_never_labelled_millimetres(self):
        finding = reports.parse_drc(drc_report(
            coordinate_units="in",
            violations=[_violation(x=1.0, y=1.0)]))[0][0]
        self.assertNotEqual(finding["x_mm"], 1.0,
                            "an inch value was stored under x_mm unconverted")
        self.assertAlmostEqual(finding["x_mm"], 25.4, places=9)

    def test_a_waiver_at_the_wrong_physical_place_does_not_match(self):
        """The same numbers in different units are different places."""
        finding = reports.parse_drc(drc_report(
            coordinate_units="in",
            violations=[_violation(x=1.0, y=2.0)]))[0][0]
        waiver = {"gate": DRC_GATE, "rule": "clearance", "category": "violations",
                  # the raw inch numbers, not the physical place
                  "items": [{"description": "Track [Net] on F.Cu",
                             "location_mm": [1.0, 2.0]}],
                  "reason": "r", "reviewed_by": "someone",
                  "reviewed_utc": "2026-08-01T00:00:00",
                  "approved_source_sha256": "a" * 64,
                  "approved_rules_sha256": "b" * 64,
                  "approved_command_sha256": "c" * 64,
                  "approved_report_sha256": "d" * 64}
        self.assertIsNone(g_checks._waived(finding, [waiver], 0.001),
                          "a waiver written in the report's raw units matched a "
                          "finding 24.4 mm away")
        waiver["items"] = [{"description": "Track [Net] on F.Cu",
                            "location_mm": [25.4, 50.8]}]
        self.assertIsNotNone(g_checks._waived(finding, [waiver], 0.001))


class NonFiniteCoordinatesAreRejected(unittest.TestCase):
    """NaN compares false against everything, including every tolerance."""

    def test_a_nan_coordinate_is_an_error_and_cannot_be_waived(self):
        doc = drc_report(violations=[_violation(x=float("nan"), y=1.0)])
        with self.assertRaises(reports.ReportSchemaError) as caught:
            reports.parse_drc(doc)
        self.assertIn("finite", str(caught.exception))

    def test_infinities_are_rejected(self):
        for bad in (float("inf"), float("-inf")):
            with self.assertRaises(reports.ReportSchemaError):
                reports.parse_drc(drc_report(violations=[_violation(x=bad)]))

    def test_nan_is_rejected_at_load_before_anything_reads_it(self):
        for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with self.assertRaises(ValueError):
                reports.loads(text)
        self.assertEqual(reports.loads('{"a": 1.5}'), {"a": 1.5})

    def test_a_nan_finding_never_reaches_waiver_matching(self):
        """Validation happens first, so there is nothing to waive."""
        waiver = {"gate": DRC_GATE, "rule": "clearance", "category": "violations",
                  "items": [{"description": "Track [Net] on F.Cu",
                             "location_mm": [0.0, 0.0]}],
                  "reason": "r", "reviewed_by": "s",
                  "reviewed_utc": "2026-08-01T00:00:00",
                  "approved_source_sha256": "a" * 64,
                  "approved_rules_sha256": "b" * 64,
                  "approved_command_sha256": "c" * 64,
                  "approved_report_sha256": "d" * 64}
        normalised = {"category": "violations", "rule": "clearance",
                      "items": [{"description": "Track [Net] on F.Cu",
                                 "uuid": None, "x_mm": float("nan"),
                                 "y_mm": float("nan")}]}
        normalised["canonical_items"] = normalised["items"]
        # Even if such a finding somehow reached the matcher, it must not match.
        self.assertIsNone(g_checks._waived(normalised, [waiver], 1e9))


class GenuineReportsStillParse(unittest.TestCase):
    """The frozen fixture's own reports are real KiCad 10 output."""

    def test_the_genuine_drc_and_erc_reports_validate(self):
        base = os.path.join(HERE, "fixtures", "reva", "project", "generated")
        drc = reports.load_report(os.path.join(base, "drc.json"))
        erc = reports.load_report(os.path.join(base, "erc.json"))
        drc_findings, drc_meta = reports.parse_drc(drc)
        erc_findings, erc_meta = reports.parse_erc(erc)
        self.assertGreater(len(drc_findings), 0)
        self.assertEqual(drc_meta["coordinate_units"], "mm")
        self.assertEqual(erc_meta["coordinate_units"], "mm")
        for finding in drc_findings:
            self.assertIsNotNone(finding["x_mm"])
            self.assertEqual(finding["source_units"], "mm")
        self.assertIsInstance(erc_findings, list)

    def test_the_vendored_drc_schema_needed_a_trailing_comma_removed(self):
        """Upstream drc.v1.json is not valid JSON; we say so rather than fix it."""
        from pcbqa import schema as schema_mod
        self.assertEqual(
            schema_mod.load_schema("drc")["__tolerated_trailing_commas__"], 1)
        self.assertEqual(
            schema_mod.load_schema("erc")["__tolerated_trailing_commas__"], 0)

if __name__ == "__main__":
    unittest.main()
