"""A rejected release must leave nothing a fabricator would accept.

The defect this file exists for: the fabrication ZIP used to be assembled
*before* validation and written straight into the run tree, so a release that
was then rejected still left a complete, orderable archive sitting on disk next
to a file that said DO NOT ORDER. Anyone who went looking for "the gerbers"
would find them.

The test drives the real `run.py release` code path to a late failure - after
the point where the archive is built - and then walks the entire output tree of
that attempt. Not the publication directories; the whole tree. A check that
only looks where the archive is supposed to be cannot detect an archive that
ended up somewhere else, which is precisely the failure being guarded against.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import run as run_cli                                    # noqa: E402
from pcbqa import cleanroom, core                        # noqa: E402
from pcbqa.core import Status                            # noqa: E402
from pcbqa.parallel import ENV_OUTPUT_ROOT               # noqa: E402

REVA = os.path.join(HERE, "boards", "reva.json")
FIXTURE = os.path.join(HERE, "fixtures", "reva", "project")


class FailedReleaseLeavesNothingOrderable(unittest.TestCase):
    """One real release attempt, forced to fail after the archive was built."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="pcbqa_norel_")
        project = os.path.join(cls.work, "project")
        shutil.copytree(FIXTURE, project)
        doc = json.load(open(REVA, encoding="utf-8"))
        doc["board_id"] = "release-no-archive-fixture"
        doc["project_root"] = project
        doc["fixture"] = {"attributes_file": os.path.abspath(
            os.path.join(HERE, "..", ".gitattributes"))}
        cls.manifest_path = os.path.join(cls.work, "manifest.json")
        with open(cls.manifest_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        cls.base = os.path.join(cls.work, "out", doc["board_id"])

        # Force the failure to happen *after* packaging: let every gate run
        # for real, then flip one mandatory gate to FAIL. This makes the test
        # independent of whether any particular board happens to be broken.
        real_run_all = core.run_all
        cls.packaged_entries = None

        def failing_run_all(context, only=None):
            results = real_run_all(context, only=only)
            for result in results:
                if result.gate_id == "CONTRACT.PLACEMENT":
                    result.failed("forced late failure, after the fabrication "
                                  "archive was assembled")
            return results

        saved = os.environ.get(ENV_OUTPUT_ROOT)
        os.environ[ENV_OUTPUT_ROOT] = cls.work
        core.run_all = failing_run_all
        try:
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                cls.exit_code = run_cli.cmd_release(cls.manifest_path)
        finally:
            core.run_all = real_run_all
            if saved is None:
                os.environ.pop(ENV_OUTPUT_ROOT, None)
            else:
                os.environ[ENV_OUTPUT_ROOT] = saved
        cls.output = captured.getvalue()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    # -- the attempt really did get as far as building an archive ----------
    def test_the_attempt_reached_the_packaging_step(self):
        """Otherwise this test would pass for the wrong reason."""
        summary = json.load(open(os.path.join(
            self.base, "release_UNSAFE_diagnostic", "clean_room.json"),
            encoding="utf-8"))
        package = next((s for s in summary["steps"] if s["step"] == "package"),
                       None)
        self.assertIsNotNone(package,
                             "the run never packaged anything, so finding no "
                             "archive proves nothing: {}".format(summary["steps"]))
        self.assertGreater(package["entries"], 0,
                           "the archive that was built was empty")

    def test_the_forced_failure_actually_blocked_the_release(self):
        self.assertNotEqual(self.exit_code, 0)
        self.assertIn("RELEASE BLOCKED", self.output)
        self.assertIn("CONTRACT.PLACEMENT", self.output)
        self.assertIn("Fabrication archive created: NO", self.output)

    # -- the property under test -------------------------------------------
    def test_no_orderable_archive_anywhere_in_the_output_tree(self):
        # The whole output tree, from the `out/` root down - not just the
        # directories a release is supposed to publish into.
        out_root = os.path.join(self.work, "out")
        found = cleanroom.orderable_archives(out_root)
        self.assertEqual(found, [],
                         "a rejected release left {} orderable archive(s): "
                         "{}".format(len(found), found))
        self.assertEqual(cleanroom.orderable_archives(self.base), [])

    def test_the_input_project_is_not_touched_by_the_sweep(self):
        """The design being released is an input; only output is swept."""
        shipped = os.path.join(self.work, "project", "generated", "release",
                               "microphone_array_v2-revA-fabrication.zip")
        self.assertTrue(os.path.isfile(shipped),
                        "the release deleted an archive belonging to the "
                        "project it was asked to release")

    def test_the_inventory_is_diagnostics_only(self):
        inventory = []
        for dirpath, _dirs, files in os.walk(self.base):
            for name in files:
                inventory.append(os.path.relpath(
                    os.path.join(dirpath, name), self.base).replace("\\", "/"))
        self.assertTrue(inventory, "the attempt produced nothing at all")
        for rel in inventory:
            lowered = rel.lower()
            for suffix in cleanroom.ORDERABLE_SUFFIXES:
                self.assertFalse(lowered.endswith(suffix),
                                 "orderable file in the output tree: " + rel)
        self.assertIn("release_UNSAFE_diagnostic/DO_NOT_ORDER.txt", inventory)

    def test_no_candidate_or_sealed_directory_exists(self):
        for forbidden in ("release_sealed", "release_candidate_UNSEALED"):
            self.assertFalse(
                os.path.exists(os.path.join(self.base, forbidden)),
                "{} was created despite a failing mandatory gate".format(
                    forbidden))

    def test_the_staging_area_was_destroyed(self):
        summary = json.load(open(os.path.join(
            self.base, "release_UNSAFE_diagnostic", "clean_room.json"),
            encoding="utf-8"))
        staging = summary["staging_root"]
        self.assertFalse(summary["promoted"])
        self.assertFalse(os.path.exists(staging),
                         "the staged package outlived the failed release: "
                         + staging)

    def test_the_diagnostic_says_plainly_that_nothing_was_produced(self):
        text = open(os.path.join(self.base, "release_UNSAFE_diagnostic",
                                 "DO_NOT_ORDER.txt"), encoding="utf-8").read()
        self.assertIn("NOT A RELEASE", text)
        self.assertIn("No sealed or orderable package was produced", text)
        self.assertIn("staged package has been destroyed", text)


class SweepIsABackstopNotThePrimaryMechanism(unittest.TestCase):
    """Staging is what keeps the promise; the sweep is belt and braces."""

    def test_the_sweep_finds_and_removes_an_archive_that_got_through(self):
        work = tempfile.mkdtemp(prefix="pcbqa_sweep_")
        self.addCleanup(shutil.rmtree, work, True)
        nested = os.path.join(work, "clean_run", "generated", "release")
        os.makedirs(nested)
        planted = os.path.join(nested, "fabrication.zip")
        with open(planted, "wb") as fh:
            fh.write(b"PK\x03\x04not really")
        also = os.path.join(work, "somewhere", "else")
        os.makedirs(also)
        with open(os.path.join(also, "panel.tar.gz"), "wb") as fh:
            fh.write(b"\x1f\x8b")

        self.assertEqual(len(cleanroom.orderable_archives(work)), 2)

        class _Stub:
            root = work
        removed = cleanroom.CleanRun.sweep_output_tree(_Stub())
        self.assertEqual(len(removed), 2, removed)
        self.assertEqual(cleanroom.orderable_archives(work), [])

    def test_every_archive_extension_a_fabricator_accepts_is_covered(self):
        for suffix in (".zip", ".7z", ".rar", ".tar", ".tgz", ".tar.gz"):
            self.assertIn(suffix, cleanroom.ORDERABLE_SUFFIXES)


if __name__ == "__main__":
    unittest.main()
