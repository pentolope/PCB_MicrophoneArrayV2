"""What the source closure covers, and whether it says the same thing twice.

A closure is an identity for "the inputs this result came from". It is only
worth having if two machines looking at the same inputs compute the same value,
and if a real change to any of those inputs changes it. Both were broken:

  * a recursive `**/*.kicad_sch` glob swept in every other board's fixture and
    every past attempt's copy, so the identity depended on what happened to be
    left lying in the validator's output tree;
  * the manifest entered provenance as its file digest, and a clean room must
    rewrite the manifest's paths, so the reports a run produced could never be
    checked from the repository that produced them;
  * text files were hashed as raw bytes, so a checkout with the other line
    ending had a different identity for a file nobody had edited.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pcbqa import canonical, cleanroom                        # noqa: E402
from pcbqa.core import Manifest                               # noqa: E402

LIVE = os.path.join(HERE, "boards", "live.json")
PROJECT = os.path.abspath(os.path.join(HERE, ".."))
ATTRIBUTES = os.path.join(PROJECT, ".gitattributes")

_SCRATCH = []


def _scratch(prefix):
    path = tempfile.mkdtemp(prefix=prefix)
    _SCRATCH.append(path)
    return path


def tearDownModule():
    for path in _SCRATCH:
        shutil.rmtree(path, ignore_errors=True)
    del _SCRATCH[:]


def _doc():
    with open(LIVE, encoding="utf-8") as fh:
        return json.load(fh)


def _manifest(document, directory=None):
    directory = directory or _scratch("pcbqa_closure_")
    path = os.path.join(directory, "manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2)
    return Manifest(path)


def _policy():
    return canonical.AttributePolicy.load(ATTRIBUTES)


def _live_closure():
    manifest = Manifest(LIVE)
    return cleanroom.source_closure(manifest, _policy())


class TheClosureCoversTheDesignAndNothingElse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.closure = _live_closure()

    def test_it_covers_the_board_the_schematic_and_the_project(self):
        for expected in ("microphone_array_v2.kicad_pcb",
                         "microphone_array_v2.kicad_sch",
                         "microphone_array_v2.kicad_pro"):
            self.assertIn(expected, self.closure)

    def test_it_covers_the_orientation_inputs(self):
        self.assertIn("tools/jlc_orientation.py", self.closure)
        evidence = [k for k in self.closure
                    if k.startswith("fabrication/jlc_orientation/")]
        raw = [k for k in evidence if "/raw/" in k]
        self.assertEqual(len(raw), 15, raw)
        self.assertEqual(len(evidence), 31, "15 raw, 15 extracts, one schema")

    def test_it_covers_the_configuration_and_the_executed_code(self):
        self.assertIn("<configuration>", self.closure)
        executed = [k for k in self.closure if k.startswith("<executed>")]
        self.assertEqual(sorted(executed),
                         ["<executed>pcbqa.cleanroom",
                          "<executed>pcbqa.gates.g_orientation",
                          "<executed>pcbqa.orientation"])

    def test_no_validator_fixture_or_output_leaks_in(self):
        """These exist on some machines and not others."""
        for key in self.closure:
            if key.startswith("<"):
                continue
            for forbidden in ("verification/fixtures/", "verification/out/",
                              "verification/", "generated/", "build/",
                              "candidates/", ".git/"):
                self.assertFalse(
                    key.startswith(forbidden),
                    "{} is in the live source closure; a closure that depends "
                    "on what is left in {} identifies nothing".format(
                        key, forbidden))

    def test_no_released_artifact_is_treated_as_an_input(self):
        for key in self.closure:
            self.assertNotIn("cpl.csv", key)
            self.assertNotIn("bom.csv", key)
            self.assertNotIn(".zip", key)


class LineEndingsAreNotAChange(unittest.TestCase):
    """A checkout is allowed either line ending; that is not an edit."""

    def _project(self, newline):
        """A copy of the closure's inputs, written with the given line ending."""
        root = _scratch("pcbqa_eol_")
        project = os.path.join(root, "project")
        os.makedirs(project)
        shutil.copy2(ATTRIBUTES, os.path.join(project, ".gitattributes"))
        manifest = Manifest(LIVE)
        for pattern in manifest.get("reports.source_closure"):
            import glob
            for path in glob.glob(os.path.join(PROJECT, pattern)):
                if not os.path.isfile(path):
                    continue
                rel = os.path.relpath(path, PROJECT)
                target = os.path.join(project, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(path, "rb") as fh:
                    body = fh.read()
                body = body.replace(b"\r\n", b"\n")
                if newline == b"\r\n":
                    body = body.replace(b"\n", b"\r\n")
                with open(target, "wb") as fh:
                    fh.write(body)
        document = _doc()
        document["project_root"] = project
        return _manifest(document, root), project

    def test_lf_and_crlf_checkouts_have_one_identity(self):
        lf, _ = self._project(b"\n")
        crlf, _ = self._project(b"\r\n")
        policy = _policy()
        left = cleanroom.source_closure(lf, policy)
        right = cleanroom.source_closure(crlf, policy)
        self.assertEqual(sorted(left), sorted(right))
        self.assertEqual(cleanroom.closure_digest(left),
                         cleanroom.closure_digest(right),
                         "the same design checked out with the other line "
                         "ending is not the same design")

    def test_a_real_edit_still_changes_the_identity(self):
        """Otherwise the fix above would be indistinguishable from ignoring it."""
        crlf, project = self._project(b"\r\n")
        policy = _policy()
        before = cleanroom.closure_digest(
            cleanroom.source_closure(crlf, policy))
        target = os.path.join(project, "fabrication", "jlc_orientation",
                              "raw", "C7668.json")
        with open(target, "ab") as fh:
            fh.write(b" ")
        after = cleanroom.closure_digest(
            cleanroom.source_closure(crlf, policy))
        self.assertNotEqual(before, after,
                            "an edited evidence body left the closure alone")

    def test_the_binding_and_checking_sides_agree_on_a_source_digest(self):
        """The report writes one identity and the gate recomputes the same one."""
        policy = _policy()
        board = os.path.join(PROJECT, "microphone_array_v2.kicad_pcb")
        rel = "microphone_array_v2.kicad_pcb"
        recorded = canonical.digest(board, policy.classify(rel))
        installed = os.path.join(PROJECT, "generated", "release", "reports",
                                 "drc.json")
        if not os.path.isfile(installed):
            self.skipTest("no installed DRC report to compare against")
        with open(installed, encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(report.get("source_sha256"), recorded,
                         "the committed DRC report is bound to a different "
                         "identity of the board than the gate computes")


class TheConfigurationIdentitySurvivesTheCleanRoom(unittest.TestCase):
    """The clean room rewrites paths. It must not rewrite the identity."""

    def _rewritten_like_a_clean_room(self, document):
        """Exactly the pointers derive_manifest() is entitled to change."""
        out = copy.deepcopy(document)
        out["board_id"] = str(out["board_id"]) + "-cleanroom"
        out["project_root"] = "fixture/project"
        out["tools"] = {"kicad_cli": "/usr/bin/kicad-cli"}
        out["fixture"] = {"hash_file": "../HASHES.json",
                          "attributes_file": "../.gitattributes"}
        out["sources"] = {k: "/elsewhere/" + v
                          for k, v in out["sources"].items()}
        out["reports"] = dict(out["reports"])
        out["reports"]["files"] = ["../../reports/*.json"]
        out["artifacts"] = dict(out["artifacts"])
        for key in ("gerber_dir", "bom", "cpl"):
            out["artifacts"][key] = "/run/build/" + key
        out["artifacts"]["cpl_fields"] = {"Designator": "Designator"}
        out["artifacts"]["cpl_origin"] = {"frame": "somewhere else"}
        out["assembly"] = dict(out["assembly"])
        out["assembly"]["bom_fields"] = {"designators": "Designator"}
        out["archive"] = dict(out["archive"])
        out["archive"]["zip"] = "/run/build/x.zip"
        out["archive"]["manifest"] = "/run/build/MANIFEST.md"
        out["archive"].pop("pre_normalization_digests", None)
        return out

    def test_rewriting_paths_does_not_change_the_identity(self):
        origin = _manifest(_doc())
        derived = _manifest(self._rewritten_like_a_clean_room(_doc()))
        self.assertNotEqual(origin.sha256, derived.sha256,
                            "the two manifests must really differ as files")
        self.assertEqual(cleanroom.configuration_identity(origin),
                         cleanroom.configuration_identity(derived),
                         "a clean room's path rewrites changed the "
                         "configuration identity, so its reports can never be "
                         "checked from the repository")

    def test_changing_a_covered_value_does_change_the_identity(self):
        origin = _manifest(_doc())
        edited = _doc()
        spec = edited["release_generation"]["cpl_orientation"]
        spec["registry"][0]["offset_deg"] = 90.0
        self.assertNotEqual(cleanroom.configuration_identity(origin),
                            cleanroom.configuration_identity(_manifest(edited)),
                            "a changed reviewed offset left the configuration "
                            "identity alone")

    def test_a_new_threshold_is_covered_without_being_listed(self):
        """Coverage is by default; only the path pointers are excluded."""
        edited = _doc()
        edited["geometry_profile"]["invented_tolerance_mm"] = 1.0
        self.assertNotEqual(cleanroom.configuration_identity(_manifest(_doc())),
                            cleanroom.configuration_identity(_manifest(edited)))

    def test_the_excluded_pointers_are_only_pointers(self):
        excluded = Manifest(LIVE).get("reports.configuration_excludes")
        for pointer in excluded:
            self.assertFalse(
                pointer.startswith("release_generation"),
                "{} would exclude release-affecting configuration".format(
                    pointer))
            self.assertFalse(pointer.startswith("release_profile"), pointer)


if __name__ == "__main__":
    unittest.main()
