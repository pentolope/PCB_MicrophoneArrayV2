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
import zipfile

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


class EarlyRejectionStillCleansUp(unittest.TestCase):
    """A release refused before it starts is still a release that failed.

    The preconditions - no release profile, no mandatory gates, no generation
    block - used to be checked before the cleanup contract was established, so
    they returned 1 without touching the managed output directory. An older
    candidate from a previous, successful-looking attempt therefore survived a
    failed command, sitting under its published name with a real ZIP in it.
    Anyone reading the directory rather than the exit code would have taken it
    for current.
    """

    def _fixture(self, board_id, mutate=None):
        work = tempfile.mkdtemp(prefix="pcbqa_early_")
        self.addCleanup(shutil.rmtree, work, True)
        project = os.path.join(work, "project")
        shutil.copytree(FIXTURE, project)
        doc = json.load(open(REVA, encoding="utf-8"))
        doc["board_id"] = board_id
        doc["project_root"] = project
        doc["fixture"] = {"attributes_file": os.path.abspath(
            os.path.join(HERE, "..", ".gitattributes"))}
        if mutate:
            mutate(doc)
        manifest_path = os.path.join(work, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        base = os.path.join(work, "out", board_id)
        return work, manifest_path, base

    @staticmethod
    def _plant_prior_candidate(base):
        """A complete-looking candidate from an earlier attempt."""
        fabrication = os.path.join(base, "release_candidate_UNSEALED",
                                   "fabrication")
        os.makedirs(fabrication)
        archive = os.path.join(fabrication, "yesterday-fabrication.zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("board-F_Cu.gbr", "G04 from an earlier run*\n")
        with open(os.path.join(base, "release_candidate_UNSEALED",
                               "UNSEALED.txt"), "w", encoding="utf-8") as fh:
            fh.write("Release CANDIDATE from a previous attempt.\n")
        return archive

    def _run(self, work, manifest_path):
        saved = os.environ.get(ENV_OUTPUT_ROOT)
        os.environ[ENV_OUTPUT_ROOT] = work
        try:
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                code = run_cli.cmd_release(manifest_path)
        finally:
            if saved is None:
                os.environ.pop(ENV_OUTPUT_ROOT, None)
            else:
                os.environ[ENV_OUTPUT_ROOT] = saved
        return code, captured.getvalue()

    def _assert_managed_output_is_clean(self, base, work):
        self.assertEqual(cleanroom.orderable_archives(os.path.join(work, "out")),
                         [], "an orderable archive survived a failed release")
        for name in cleanroom.CANDIDATE_DIR_NAMES:
            self.assertFalse(
                os.path.exists(os.path.join(base, name)),
                "{} survived a failed release".format(name))
        leftovers = []
        for dirpath, _dirs, files in os.walk(os.path.join(work, "out")):
            for name in files:
                if name.lower().endswith(cleanroom.ORDERABLE_SUFFIXES):
                    leftovers.append(os.path.join(dirpath, name))
        self.assertEqual(leftovers, [])

    # -- each precondition, with a prior candidate already in place --------
    def test_a_missing_release_profile_removes_a_prior_candidate(self):
        work, manifest_path, base = self._fixture(
            "early-no-profile", lambda doc: doc.pop("release_profile"))
        os.makedirs(base, exist_ok=True)
        archive = self._plant_prior_candidate(base)
        self.assertTrue(os.path.isfile(archive))

        code, output = self._run(work, manifest_path)
        self.assertEqual(code, 1, output)
        self.assertIn("declares no release_profile", output)
        self._assert_managed_output_is_clean(base, work)

    def test_an_empty_mandatory_gate_list_removes_a_prior_candidate(self):
        def mutate(doc):
            doc["release_profile"]["mandatory_gates"] = []
        work, manifest_path, base = self._fixture("early-no-gates", mutate)
        os.makedirs(base, exist_ok=True)
        self._plant_prior_candidate(base)

        code, output = self._run(work, manifest_path)
        self.assertEqual(code, 1, output)
        self.assertIn("names no mandatory gates", output)
        self._assert_managed_output_is_clean(base, work)

    def test_a_missing_generation_block_removes_a_prior_candidate(self):
        work, manifest_path, base = self._fixture(
            "early-no-generation", lambda doc: doc.pop("release_generation"))
        os.makedirs(base, exist_ok=True)
        self._plant_prior_candidate(base)

        code, output = self._run(work, manifest_path)
        self.assertEqual(code, 1, output)
        self.assertIn("no release_generation block", output)
        self._assert_managed_output_is_clean(base, work)

    def test_a_validation_failure_also_removes_a_prior_candidate(self):
        """Rev A fails its gates; the prior candidate must go with it."""
        work, manifest_path, base = self._fixture("early-validation-failure")
        os.makedirs(base, exist_ok=True)
        self._plant_prior_candidate(base)

        code, output = self._run(work, manifest_path)
        self.assertEqual(code, 1, output[-1500:])
        self._assert_managed_output_is_clean(base, work)
        self.assertTrue(os.path.isfile(os.path.join(
            base, "release_UNSAFE_diagnostic", "DO_NOT_ORDER.txt")))

    def test_a_successful_release_still_publishes_exactly_one_candidate(self):
        """The control: cleanup must not eat a release that earned publication."""
        work, manifest_path, base = self._fixture("early-success-control")
        os.makedirs(base, exist_ok=True)
        self._plant_prior_candidate(base)

        real_run_all = core.run_all

        def all_pass(context, only=None):
            results = real_run_all(context, only=only)
            for result in results:
                if result.status != Status.NOT_APPLICABLE:
                    result.passed(result.reason or "forced for this test")
            return results

        core.run_all = all_pass
        try:
            code, output = self._run(work, manifest_path)
        finally:
            core.run_all = real_run_all

        self.assertEqual(code, 0, output[-2000:])
        candidate = os.path.join(base, "release_candidate_UNSEALED")
        self.assertTrue(os.path.isdir(candidate))
        archives = cleanroom.orderable_archives(os.path.join(work, "out"))
        self.assertEqual(len(archives), 1,
                         "expected exactly one published archive, found "
                         "{}".format(archives))
        # realpath on both sides: Windows hands back 8.3 short names ("PENTOL~1")
        # in one and the expanded form in the other, and comparing the two
        # verbatim would fail on a correct result.
        self.assertTrue(
            os.path.realpath(archives[0]).startswith(
                os.path.realpath(candidate)),
            "the surviving archive is not the published one: " + archives[0])
        # And it is this run's archive, not the one planted beforehand.
        self.assertNotIn("yesterday-fabrication.zip", archives[0])



class FailuresBeforeTheManifestStillCleanUp(unittest.TestCase):
    """Cleanup is established before anything that can fail is attempted.

    Importing the gate modules and constructing the manifest are both able to
    raise, and both used to happen before the cleanup contract existed. A
    release that died in either place returned nonzero having touched nothing -
    leaving an earlier candidate, complete with its archive, sitting under its
    published name.
    """

    def _fixture(self, board_id, manifest_text=None):
        work = tempfile.mkdtemp(prefix="pcbqa_pre_")
        self.addCleanup(shutil.rmtree, work, True)
        project = os.path.join(work, "project")
        shutil.copytree(FIXTURE, project)
        manifest_path = os.path.join(work, "manifest.json")
        if manifest_text is None:
            doc = json.load(open(REVA, encoding="utf-8"))
            doc["board_id"] = board_id
            doc["project_root"] = project
            doc["fixture"] = {"attributes_file": os.path.abspath(
                os.path.join(HERE, "..", ".gitattributes"))}
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2)
        else:
            with open(manifest_path, "w", encoding="utf-8") as fh:
                fh.write(manifest_text)
        base = os.path.join(work, "out", board_id)
        os.makedirs(base, exist_ok=True)
        return work, manifest_path, base

    @staticmethod
    def _plant(base):
        fabrication = os.path.join(base, "release_candidate_UNSEALED",
                                   "fabrication")
        os.makedirs(fabrication, exist_ok=True)
        archive = os.path.join(fabrication, "yesterday-fabrication.zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("board-F_Cu.gbr", "G04 from an earlier run*\n")
        return archive

    def _run(self, work, manifest_path):
        saved = os.environ.get(ENV_OUTPUT_ROOT)
        os.environ[ENV_OUTPUT_ROOT] = work
        try:
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                code = run_cli.cmd_release(manifest_path)
        finally:
            if saved is None:
                os.environ.pop(ENV_OUTPUT_ROOT, None)
            else:
                os.environ[ENV_OUTPUT_ROOT] = saved
        return code, captured.getvalue()

    def _assert_clean(self, work, base):
        self.assertEqual(cleanroom.orderable_archives(os.path.join(work, "out")),
                         [], "an orderable archive survived")
        for name in cleanroom.CANDIDATE_DIR_NAMES:
            self.assertFalse(os.path.exists(os.path.join(base, name)),
                             "{} survived".format(name))

    def test_a_gate_import_failure_removes_a_prior_candidate(self):
        work, manifest_path, base = self._fixture("pre-import-failure")
        archive = self._plant(base)
        self.assertTrue(os.path.isfile(archive))

        real = run_cli._load_gates

        def broken():
            raise ImportError("simulated failure importing a gate module")

        run_cli._load_gates = broken
        try:
            code, output = self._run(work, manifest_path)
        finally:
            run_cli._load_gates = real

        self.assertEqual(code, 1, output)
        self.assertIn("simulated failure importing a gate module", output)
        self._assert_clean(work, base)

    def test_a_malformed_manifest_removes_a_prior_candidate(self):
        """Unparseable JSON, but the board it belongs to is still legible."""
        text = ('{\n  "board_id": "pre-malformed",\n'
                '  "schema_version": 2,\n'
                '  "sources": { "pcb": "x.kicad_pcb", },\n}')
        work, manifest_path, base = self._fixture("pre-malformed", text)
        self._plant(base)

        code, output = self._run(work, manifest_path)
        self.assertEqual(code, 1, output)
        self._assert_clean(work, base)

    def test_a_manifest_of_the_wrong_schema_version_removes_a_prior_candidate(self):
        work, manifest_path, base = self._fixture("pre-wrong-schema")
        doc = json.load(open(manifest_path, encoding="utf-8"))
        doc["schema_version"] = 99
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        self._plant(base)

        code, output = self._run(work, manifest_path)
        self.assertEqual(code, 1, output)
        self.assertIn("schema_version", output)
        self._assert_clean(work, base)

    def test_a_manifest_naming_no_board_is_refused_without_guessing(self):
        """With no board id there is no managed directory, and none is invented."""
        work, manifest_path, _base = self._fixture("pre-no-board", "{ not json")
        code, output = self._run(work, manifest_path)
        self.assertEqual(code, 1, output)
        self.assertIn("cannot identify the board", output)

    def test_the_board_id_survives_a_manifest_that_will_not_parse(self):
        work = tempfile.mkdtemp(prefix="pcbqa_bid_")
        self.addCleanup(shutil.rmtree, work, True)
        path = os.path.join(work, "m.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{ "board_id": "legible-anyway", oops }')
        saved = os.environ.get(ENV_OUTPUT_ROOT)
        os.environ[ENV_OUTPUT_ROOT] = work
        try:
            resolved = run_cli.managed_output_dir(path)
        finally:
            if saved is None:
                os.environ.pop(ENV_OUTPUT_ROOT, None)
            else:
                os.environ[ENV_OUTPUT_ROOT] = saved
        self.assertTrue(resolved.endswith(os.path.join("out", "legible-anyway")),
                        resolved)


class PromotionIsTransactional(unittest.TestCase):
    """A candidate exists in the output tree, or it does not. Never half.

    Promotion used to write the candidate directory in place: make the
    directory, copy the fabrication package in, then copy reports, then write
    metadata. Anything that threw after the first copy left a directory
    containing a complete, orderable ZIP - and, because promotion had
    "started", the cleanup path skipped it.

    These tests force every gate to PASS so the promotion path actually runs.
    That is a statement about the release machinery, not about any board: the
    point is what happens between "all gates passed" and "candidate on disk".
    """

    def _fixture(self):
        work = tempfile.mkdtemp(prefix="pcbqa_promo_")
        self.addCleanup(shutil.rmtree, work, True)
        project = os.path.join(work, "project")
        shutil.copytree(FIXTURE, project)
        doc = json.load(open(REVA, encoding="utf-8"))
        doc["board_id"] = "promotion-fixture"
        doc["project_root"] = project
        doc["fixture"] = {"attributes_file": os.path.abspath(
            os.path.join(HERE, "..", ".gitattributes"))}
        manifest_path = os.path.join(work, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        return work, manifest_path, os.path.join(work, "out", doc["board_id"])

    def _release(self, work, manifest_path, inject=None):
        """Run the real release with every gate forced to PASS."""
        real_run_all = core.run_all

        def all_pass(context, only=None):
            results = real_run_all(context, only=only)
            for result in results:
                if result.status != Status.NOT_APPLICABLE:
                    result.passed(result.reason or "forced for this test")
            return results

        real_commit = cleanroom.CleanRun.commit_candidate
        saved = os.environ.get(ENV_OUTPUT_ROOT)
        os.environ[ENV_OUTPUT_ROOT] = work
        core.run_all = all_pass
        if inject is not None:
            cleanroom.CleanRun.commit_candidate = inject
        try:
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                code = run_cli.cmd_release(manifest_path)
        finally:
            core.run_all = real_run_all
            cleanroom.CleanRun.commit_candidate = real_commit
            if saved is None:
                os.environ.pop(ENV_OUTPUT_ROOT, None)
            else:
                os.environ[ENV_OUTPUT_ROOT] = saved
        return code, captured.getvalue()

    # -- the control: it really does succeed when nothing is injected ------
    def test_the_release_succeeds_and_produces_a_candidate(self):
        work, manifest_path, base = self._fixture()
        code, output = self._release(work, manifest_path)
        self.assertEqual(code, 0, output[-3000:])
        candidate = os.path.join(base, "release_candidate_UNSEALED")
        self.assertTrue(os.path.isdir(candidate), output[-2000:])
        archives = cleanroom.orderable_archives(candidate)
        self.assertEqual(len(archives), 1,
                         "a successful release must produce exactly one "
                         "orderable archive: {}".format(archives))
        for name in ("UNSEALED.txt", "validation.json", "clean_room.json",
                     "reports", "fabrication"):
            self.assertTrue(os.path.exists(os.path.join(candidate, name)),
                            "candidate is missing " + name)
        summary = json.load(open(os.path.join(candidate, "clean_room.json"),
                                 encoding="utf-8"))
        # This snapshot is written *before* the commit, by design: the commit
        # must be the last operation, so nothing inside the candidate can
        # record that it happened. The evidence that it did is the candidate
        # being here at all, under its final name, with a zero exit status.
        self.assertFalse(summary["release_succeeded"])
        self.assertFalse(os.path.exists(summary["staging_root"]),
                         "staging outlived a successful release")
        self.assertIn("Unsealed release candidate", output)

    # -- injected failure after the ZIP is staged, before promotion ends ---
    def _assert_nothing_orderable(self, base, work, code, output):
        self.assertNotEqual(code, 0, output[-2000:])
        self.assertFalse(
            os.path.exists(os.path.join(base, "release_candidate_UNSEALED")),
            "a candidate directory survived a failed promotion")
        self.assertFalse(os.path.exists(os.path.join(base, "release_sealed")))
        out_root = os.path.join(work, "out")
        found = cleanroom.orderable_archives(out_root)
        self.assertEqual(found, [],
                         "failed promotion left {} orderable archive(s): "
                         "{}".format(len(found), found))
        self.assertTrue(
            os.path.isfile(os.path.join(base, "release_UNSAFE_diagnostic",
                                        "DO_NOT_ORDER.txt")),
            "the unsafe diagnostic must still be there")

    def test_an_exception_during_promotion_leaves_nothing_orderable(self):
        work, manifest_path, base = self._fixture()

        def explode(self_run, destination):
            # The fabrication package has already been copied into the pending
            # candidate by stage_candidate() at this point - the exact window
            # that used to leave an orderable ZIP behind.
            assert self_run.pending and os.path.isdir(
                os.path.join(self_run.pending, "fabrication"))
            raise RuntimeError("injected failure during promotion")

        code, output = self._release(work, manifest_path, inject=explode)
        self._assert_nothing_orderable(base, work, code, output)
        self.assertIn("injected failure during promotion", output)

    def test_an_interrupt_during_promotion_leaves_nothing_orderable(self):
        work, manifest_path, base = self._fixture()

        def interrupt(self_run, destination):
            raise KeyboardInterrupt()

        code, output = self._release(work, manifest_path, inject=interrupt)
        self.assertEqual(code, 130)
        self._assert_nothing_orderable(base, work, code, output)

    def test_a_partial_promotion_is_swept(self):
        """Even if a candidate directory somehow lands, it does not survive."""
        work, manifest_path, base = self._fixture()

        def half(self_run, destination):
            os.makedirs(destination, exist_ok=True)
            shutil.copytree(os.path.join(self_run.pending, "fabrication"),
                            os.path.join(destination, "fabrication"))
            raise RuntimeError("injected failure after a partial copy")

        code, output = self._release(work, manifest_path, inject=half)
        self._assert_nothing_orderable(base, work, code, output)

    def test_success_is_recorded_only_by_a_completed_commit(self):
        work, manifest_path, base = self._fixture()
        run = cleanroom.CleanRun.__new__(cleanroom.CleanRun)
        self.assertFalse(getattr(run, "succeeded", False),
                         "release_succeeded must not default to true")


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
