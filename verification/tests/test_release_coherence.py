"""A release package must agree with itself, and be caught when it does not.

The defect these tests exist for is not a broken file. Every file was well
formed; they came from two different clean-room runs, and the set was a lie -
a validation report describing an archive that was not there, beside an archive
no report described, with a prose note explaining the discrepancy.

So every test here damages the package the way that actually happens: it puts
a file from an *earlier, valid* release beside files from a later one. Nothing
is corrupted, nothing is truncated, and a checker that only validates files one
at a time passes every one of them.
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

from pcbqa import coherence                                   # noqa: E402
from pcbqa import core                                        # noqa: E402
from pcbqa.core import Context, Manifest, Status              # noqa: E402
from pcbqa.gates import g_provenance                          # noqa: E402,F401

LIVE = os.path.join(HERE, "boards", "live.json")
PROJECT = os.path.abspath(os.path.join(HERE, ".."))
INSTALLED = os.path.join(PROJECT, "generated", "release")
GATE = "PROV.RELEASE_COHERENCE"


def _names():
    return coherence.member_names(Manifest(LIVE))


def _older_releases():
    """Previously published packages, newest first. Real ones, not fabricated."""
    root = os.path.join(HERE, "out")
    out = []
    for board in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        published = os.path.join(root, board, "published")
        if not os.path.isdir(published):
            continue
        for name in sorted(os.listdir(published), reverse=True):
            path = os.path.join(published, name)
            if os.path.isdir(path):
                out.append(path)
    return out


class TheInstalledReleaseIsOneRun(unittest.TestCase):

    def test_it_is_coherent(self):
        problems, facts = coherence.check(INSTALLED, _names())
        self.assertEqual(problems, [], "the committed release is not one run")
        self.assertEqual(facts["stage"], "installed")
        self.assertEqual(facts["verdict"], "ACCEPTED")
        self.assertIsInstance(facts["source_closure_sha256"], str,
                              "more than one source closure is named")

    def test_the_gate_agrees(self):
        ctx = Context(Manifest(LIVE), tempfile.mkdtemp(prefix="pcbqa_coh_"))
        result = {r.gate_id: r.to_dict()
                  for r in core.run_all(ctx, only={GATE})}[GATE]
        self.assertEqual(result["status"], Status.PASS, result["findings"])

    def test_the_receipt_accounts_for_every_file_but_itself(self):
        receipt = json.load(open(os.path.join(INSTALLED,
                                              coherence.RECEIPT_NAME),
                                 encoding="utf-8"))
        self.assertNotIn(coherence.RECEIPT_NAME, receipt["files"])
        listed = set(receipt["files"])
        actual = set(coherence.inventory(INSTALLED))
        self.assertEqual(listed, actual)
        self.assertTrue(receipt["what_is_hashed"])


class AFileFromAnotherRunIsCaught(unittest.TestCase):
    """Each test swaps in one file from a genuinely earlier release."""

    @classmethod
    def setUpClass(cls):
        cls.names = _names()
        cls.donors = [p for p in _older_releases()
                      if os.path.isfile(os.path.join(p, cls.names["archive"]))]
        if not cls.donors:
            raise unittest.SkipTest("no earlier published release to draw from")

    def _package_with(self, member, donor_rel=None):
        """A copy of the installed release with one file taken from an older one."""
        work = tempfile.mkdtemp(prefix="pcbqa_mutate_")
        root = os.path.join(work, "release")
        shutil.copytree(INSTALLED, root)
        donor_rel = donor_rel or member
        for donor in self.donors:
            source = os.path.join(donor, donor_rel)
            if os.path.isfile(source) and coherence.sha256_file(source) != \
                    coherence.sha256_file(os.path.join(root, member)):
                shutil.copy2(source, os.path.join(root, member))
                return root, donor
        self.skipTest("no earlier release carries a different " + donor_rel)

    def _problems(self, member, donor_rel=None):
        root, _donor = self._package_with(member, donor_rel)
        problems, _facts = coherence.check(root, self.names)
        self.assertTrue(problems,
                        "swapping {} for an older one was not caught".format(
                            member))
        return problems, root

    def test_an_older_archive_is_caught(self):
        problems, _root = self._problems(self.names["archive"])
        blamed = " ".join(json.dumps(p) for p in problems)
        self.assertIn(self.names["archive"], blamed)
        self.assertIn("different", blamed)

    def test_an_older_release_manifest_is_caught(self):
        problems, _root = self._problems(self.names["manifest"])
        self.assertTrue(any("digest" in p["issue"] or "closure" in p["issue"]
                            or "receipt" in p["issue"] for p in problems),
                        problems)

    def test_an_older_check_report_is_caught(self):
        problems, _root = self._problems("reports/drc.json")
        blamed = " ".join(json.dumps(p) for p in problems)
        self.assertIn("drc.json", blamed)

    def test_an_older_clean_room_record_is_caught(self):
        problems, _root = self._problems(self.names["clean_room"])
        blamed = " ".join(json.dumps(p) for p in problems)
        self.assertIn(self.names["clean_room"], blamed)

    def test_an_older_validation_report_is_caught(self):
        problems, _root = self._problems(self.names["validation"])
        blamed = " ".join(json.dumps(p) for p in problems)
        self.assertIn(self.names["validation"], blamed)

    def test_a_prose_note_does_not_rescue_any_of_them(self):
        """The exact thing that was tried before: explain it and move on."""
        root, _donor = self._package_with(self.names["archive"])
        with open(os.path.join(root, "PROVENANCE_NOTE.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# Why the archive is older\n\nThe Gerbers differ only "
                     "in KiCad timestamp comments, so this is fine.\n")
        problems, _facts = coherence.check(root, self.names)
        self.assertTrue(problems, "a note made the mismatch pass")


class AnIncompletePackageIsCaught(unittest.TestCase):

    def setUp(self):
        self.names = _names()
        self.work = tempfile.mkdtemp(prefix="pcbqa_incomplete_")
        self.root = os.path.join(self.work, "release")
        shutil.copytree(INSTALLED, self.root)

    def test_a_missing_receipt_is_caught(self):
        os.remove(os.path.join(self.root, coherence.RECEIPT_NAME))
        problems, _facts = coherence.check(self.root, self.names)
        self.assertTrue(any("receipt" in p["issue"] for p in problems),
                        problems)

    def test_an_extra_file_is_caught(self):
        with open(os.path.join(self.root, "left_over.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("from some other run\n")
        problems, _facts = coherence.check(self.root, self.names)
        self.assertTrue(any(p.get("file") == "left_over.txt"
                            for p in problems), problems)

    def test_a_deleted_member_is_caught(self):
        os.remove(os.path.join(self.root, "reports", "erc.json"))
        problems, _facts = coherence.check(self.root, self.names)
        self.assertTrue(any("reports/erc.json" == p.get("file")
                            for p in problems), problems)

    def test_a_rejected_verdict_cannot_ship(self):
        path = os.path.join(self.root, self.names["validation"])
        doc = json.load(open(path, encoding="utf-8"))
        doc["summary"]["verdict"] = "REJECTED"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        problems, _facts = coherence.check(self.root, self.names)
        self.assertTrue(any("did not accept" in p["issue"] for p in problems),
                        problems)

    def test_a_candidate_package_is_recognised_rather_than_failed(self):
        """Mid-build there are no reports yet, and that is not incoherence."""
        for name in (self.names["validation"], self.names["clean_room"],
                     self.names["unsealed"], coherence.RECEIPT_NAME):
            os.remove(os.path.join(self.root, name))
        shutil.rmtree(os.path.join(self.root, "reports"))
        problems, facts = coherence.check(self.root, self.names,
                                          require_receipt=False)
        self.assertEqual(problems, [], problems)
        self.assertEqual(facts["stage"], "candidate")


if __name__ == "__main__":
    unittest.main()
