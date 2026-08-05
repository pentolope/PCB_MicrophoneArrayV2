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
        doc = {"$schema": "https://schemas.kicad.org/drc.v9.json",
               "date": "d", "kicad_version": "10.0.5", "source": "b.kicad_pcb",
               "ignored_checks": [], "included_severities": ["error"],
               "violations": [], "unconnected_items": [], "schematic_parity": []}
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(doc)
        doc["$schema"] = "https://schemas.kicad.org/drc.v1.json"
        self.assertEqual(reports.parse_drc(doc)[0], [])

    def test_an_unsupported_kicad_major_version_is_refused(self):
        doc = {"$schema": "https://schemas.kicad.org/drc.v1.json",
               "date": "d", "kicad_version": "11.0.0", "source": "b.kicad_pcb",
               "ignored_checks": [], "included_severities": ["error"],
               "violations": [], "unconnected_items": [], "schematic_parity": []}
        with self.assertRaises(reports.ReportSchemaError):
            reports.parse_drc(doc)

    def test_a_missing_section_is_refused(self):
        base = {"$schema": "https://schemas.kicad.org/drc.v1.json",
                "date": "d", "kicad_version": "10.0.5", "source": "b.kicad_pcb",
                "ignored_checks": [], "included_severities": ["error"],
                "violations": [], "unconnected_items": [],
                "schematic_parity": []}
        for section in ("violations", "unconnected_items", "schematic_parity",
                        "included_severities", "ignored_checks", "source"):
            doc = dict(base)
            doc.pop(section)
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="missing {} was accepted".format(section)):
                reports.parse_drc(doc)

    def test_a_malformed_finding_is_refused(self):
        base = {"$schema": "https://schemas.kicad.org/drc.v1.json",
                "date": "d", "kicad_version": "10.0.5", "source": "b.kicad_pcb",
                "ignored_checks": [], "included_severities": ["error"],
                "unconnected_items": [], "schematic_parity": []}
        for bad in ({"severity": "error"},                 # no rule type
                    {"type": "", "severity": "error"},     # empty rule type
                    {"type": "clearance", "severity": "catastrophic"},
                    {"type": "clearance", "items": "not-a-list"},
                    "not-an-object"):
            with self.assertRaises(reports.ReportSchemaError,
                                   msg="{!r} was accepted".format(bad)):
                reports.parse_drc(dict(base, violations=[bad]))

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
                "objects": ["T1", "T2"], "location_mm": [1.0, 2.0],
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


if __name__ == "__main__":
    unittest.main()
