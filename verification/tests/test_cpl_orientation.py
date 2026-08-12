"""The reviewed orientation registry, the generator that uses it, and the gate.

Two corrections reach a placement angle, and confusing them is expensive.
Normalisation moves an angle into the range the assembly house reads and turns
nothing. A library-zero offset does turn the part, and only where the house's
library and the layout disagree about the part's zero.

The failure that started this was neither: a part whose orientation nobody had
checked shipped at whatever the layout said, because the lookup defaulted to
zero. So the case these tests care about most is the *absent* entry, and it is
driven through the real generation code rather than by editing an output.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pcbqa import core                                          # noqa: E402
from pcbqa.core import Context, Manifest, Status                # noqa: E402
from pcbqa.gates import g_orientation                           # noqa: E402,F401
from pcbqa.orientation import (OrientationError, Registry,      # noqa: E402
                               apply_to_rows, normalise)

LIVE = os.path.join(HERE, "boards", "live.json")
GATE = "CPL.ORIENTATION"
PROJECT = os.path.abspath(os.path.join(HERE, ".."))
CPL = os.path.join(PROJECT, "generated", "release", "cpl.csv")

# The angles the four corrected parts must ship at. Recorded here as plain
# numbers so a change to the registry has to be argued for twice.
EXPECTED_U = {"U1": 180.0, "U2": 270.0, "U3": 270.0, "U4": 270.0}
# A sample of the 48 whose JLC-revised values were never supplied. Their
# fractional angles must survive, normalised and otherwise untouched.
EXPECTED_FRACTIONAL = {
    "CB1": 33.75, "CB3": 213.75, "CM2": 202.5, "CM10": 22.5,
    "MK1": 270.0, "MK2": 292.5, "RD8": 337.5, "RV16": 337.5,
}


def _manifest_doc():
    with open(LIVE, encoding="utf-8") as fh:
        return json.load(fh)


def _spec():
    return _manifest_doc()["release_generation"]["cpl_orientation"]


def _cpl_rows(path=CPL):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _board_numbers_and_angles():
    import pcbnew
    board = pcbnew.LoadBoard(os.path.join(
        PROJECT, "microphone_array_v2.kicad_pcb"))
    out = {}
    for fp in board.Footprints():
        number = ""
        for field in fp.GetFields():
            if field.GetName() == "LCSC" and field.GetText().strip():
                number = field.GetText().strip()
        out[fp.GetReference()] = (number, fp.GetOrientationDegrees())
    return out


def _run_gate(manifest_path):
    ctx = Context(Manifest(manifest_path),
                  tempfile.mkdtemp(prefix="pcbqa_orient_work_"))
    results = core.run_all(ctx, only={GATE})
    return {r.gate_id: r.to_dict() for r in results}[GATE]


# ---------------------------------------------------------------------------
# the registry as a document
# ---------------------------------------------------------------------------

class RegistryIsReviewedAndComplete(unittest.TestCase):

    def setUp(self):
        self.spec = _spec()
        self.registry = Registry(self.spec)

    def test_it_is_internally_well_formed(self):
        self.assertEqual(self.registry.defects(), [])

    def test_every_populated_part_has_an_entry(self):
        """Coverage judged from the board, not from the registry's own list."""
        placed = {row["Designator"] for row in _cpl_rows()}
        board = _board_numbers_and_angles()
        missing = sorted(ref for ref in placed
                         if not self.registry.covers(board[ref][0]))
        self.assertEqual(missing, [], "populated parts with no reviewed entry")

    def test_parts_needing_no_turn_are_registered_rather_than_defaulted(self):
        """An explicit zero is a review; a missing entry is not."""
        zeros = [lcsc for lcsc, row in self.registry.entries.items()
                 if float(row["offset_deg"]) == 0.0]
        self.assertGreater(len(zeros), 1,
                           "this board has parts that need no turn; each must "
                           "still be reviewed explicitly")
        for lcsc in zeros:
            row = self.registry.entries[lcsc]
            self.assertEqual(row["review_status"], "reviewed")
            self.assertTrue(str(row["evidence_file"]).strip())

    def test_every_entry_cites_evidence_that_exists_and_matches(self):
        for lcsc, row in sorted(self.registry.entries.items()):
            path = os.path.join(PROJECT, row["evidence_file"])
            self.assertTrue(os.path.isfile(path),
                            "{} cites missing evidence".format(lcsc))
            with open(path, encoding="utf-8") as fh:
                evidence = json.load(fh)
            self.assertEqual(evidence["response_sha256"],
                             row["evidence_sha256"],
                             "{}: recorded digest is not the evidence's"
                             .format(lcsc))
            self.assertTrue(evidence["source_url"])
            self.assertTrue(evidence["retrieved_utc"])
            self.assertTrue(evidence["pads"])

    def test_the_offsets_are_what_the_evidence_derives(self):
        """The registry is checked against JLC's geometry, not against itself."""
        sys.path.insert(0, os.path.join(PROJECT, "tools"))
        import jlc_orientation
        derived = jlc_orientation.derive("LCSC")
        for lcsc, row in sorted(self.registry.entries.items()):
            self.assertIn(lcsc, derived)
            self.assertTrue(derived[lcsc]["decisive"],
                            "{}: evidence does not decide".format(lcsc))
            self.assertAlmostEqual(
                float(row["offset_deg"]),
                float(derived[lcsc]["best_offset_deg"]), places=3,
                msg="{}: registry and evidence disagree".format(lcsc))

    def test_the_undocumented_edits_are_recorded(self):
        block = self.spec["undocumented_production_edits"]
        self.assertEqual(len(block["references"]), 48)
        self.assertIn("unavailable", block["verification_limit"])


# ---------------------------------------------------------------------------
# the arithmetic
# ---------------------------------------------------------------------------

class NormalisationAndLookup(unittest.TestCase):

    def test_normalisation_covers_the_turn(self):
        for angle, want in ((-90, 270), (-157.5, 202.5), (0, 0), (359.9, 359.9),
                            (360, 0), (-0.0001, 359.9999)):
            self.assertAlmostEqual(normalise(angle), want, places=4)

    def test_an_unknown_part_raises_rather_than_defaulting(self):
        registry = Registry(_spec())
        with self.assertRaises(OrientationError):
            registry.offset("C-NOT-A-PART")
        with self.assertRaises(OrientationError):
            registry.offset("")

    def test_a_registered_zero_is_not_the_same_as_no_entry(self):
        registry = Registry(_spec())
        zero = next(lcsc for lcsc, row in registry.entries.items()
                    if float(row["offset_deg"]) == 0.0)
        self.assertEqual(registry.offset(zero), 0.0)
        with self.assertRaises(OrientationError):
            registry.offset(zero + "X")


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------

class GenerationRefusesAnUnreviewedPart(unittest.TestCase):
    """The regression test for the defect that started this.

    Not an edited output: the registry loses U2's part number and the real
    generation code is asked to produce the placement angles from it.
    """

    def _generate(self, spec):
        """What the release does: the populated placements, angles from the
        board, run through the same code the generator calls.

        Only populated parts, because that is what the position export emits -
        the hand-fitted connectors and the test pads are excluded from it and
        never reach a machine."""
        board = _board_numbers_and_angles()
        populated = sorted(row["Designator"] for row in _cpl_rows())
        rows = [{"Designator": ref, "Rotation": "{:.6f}".format(board[ref][1])}
                for ref in populated]
        numbers = {ref: board[ref][0] for ref in populated}
        return apply_to_rows(rows, Registry(spec), numbers,
                             "Designator", "Rotation")

    def test_the_intact_registry_generates_every_angle(self):
        applied, problems = self._generate(_spec())
        self.assertEqual(problems, [])
        self.assertIn("U2", applied)

    def test_removing_u2s_part_blocks_generation_naming_that_part(self):
        spec = copy.deepcopy(_spec())
        before = len(spec["registry"])
        spec["registry"] = [row for row in spec["registry"]
                            if row["lcsc"] != "C7668"]
        self.assertEqual(len(spec["registry"]), before - 1,
                         "C7668 must have been in the registry to remove")

        applied, problems = self._generate(spec)

        self.assertNotIn("U2", applied,
                         "U2 must not receive an angle without a reviewed "
                         "entry")
        blamed = [p for p in problems if p.get("reference") == "U2"]
        self.assertTrue(blamed, "generation must fail for U2 specifically: {}"
                        .format(problems))
        self.assertEqual(blamed[0].get("lcsc"), "C7668")
        self.assertIn("no reviewed orientation entry", blamed[0]["issue"])
        # and nothing else is collateral damage
        self.assertEqual([p["reference"] for p in problems], ["U2"])

    def test_the_gate_also_refuses_it(self):
        """Belt and braces: if a file were produced anyway, the gate objects."""
        spec_doc = _manifest_doc()
        spec_doc["release_generation"]["cpl_orientation"]["registry"] = [
            row for row
            in spec_doc["release_generation"]["cpl_orientation"]["registry"]
            if row["lcsc"] != "C7668"]
        work = tempfile.mkdtemp(prefix="pcbqa_orient_missing_")
        spec_doc["project_root"] = PROJECT
        spec_doc["fixture"] = {
            "attributes_file": os.path.join(PROJECT, ".gitattributes")}
        path = os.path.join(work, "manifest.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec_doc, fh, indent=2)
        gate = _run_gate(path)
        self.assertEqual(gate["status"], Status.FAIL)
        self.assertTrue(
            any(f.get("lcsc") == "C7668" or f.get("reference") == "U2"
                for f in gate["findings"]),
            gate["findings"])


# ---------------------------------------------------------------------------
# the shipped file
# ---------------------------------------------------------------------------

class ShippedPlacementsAreCorrect(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = _cpl_rows()
        cls.angle = {row["Designator"]: float(row["Rotation"])
                     for row in cls.rows}

    def test_the_gate_passes(self):
        gate = _run_gate(LIVE)
        self.assertEqual(gate["status"], Status.PASS, gate.get("findings"))

    def test_every_angle_is_normalised(self):
        for ref, angle in self.angle.items():
            self.assertGreaterEqual(angle, 0.0, ref)
            self.assertLess(angle, 360.0, ref)

    def test_the_four_corrected_parts_ship_their_reviewed_angles(self):
        for ref, want in EXPECTED_U.items():
            self.assertAlmostEqual(self.angle[ref], want, places=3,
                                   msg="{} shipped {}".format(ref,
                                                              self.angle[ref]))

    def test_parts_sharing_a_number_share_a_correction(self):
        board = _board_numbers_and_angles()
        turns = {}
        for ref, shipped in self.angle.items():
            number, rotation = board[ref]
            turns.setdefault(number, set()).add(round((shipped - rotation)
                                                      % 360.0, 4))
        for number, seen in sorted(turns.items()):
            self.assertEqual(len(seen), 1,
                             "{} was corrected {} different ways".format(
                                 number, len(seen)))
        u3, u4 = board["U3"][0], board["U4"][0]
        self.assertEqual(u3, u4)
        self.assertAlmostEqual(self.angle["U3"], self.angle["U4"], places=4)

    def test_the_fractional_angles_survive(self):
        """The 48 JLC edited keep their submitted values, only normalised."""
        for ref, want in EXPECTED_FRACTIONAL.items():
            self.assertAlmostEqual(self.angle[ref], want, places=4,
                                   msg="{} shipped {}".format(ref,
                                                              self.angle[ref]))
        # However many placements sit off the 45-degree grid on the board,
        # exactly that many must sit off it in the shipped file: a rounding
        # policy applied anywhere would show up as a smaller count.
        board = _board_numbers_and_angles()
        on_board = {ref for ref, (_n, angle) in board.items()
                    if ref in self.angle and angle % 45.0 not in (0.0,)}
        shipped = {ref for ref, angle in self.angle.items()
                   if angle % 45.0 > 1e-6}
        self.assertEqual(shipped, on_board,
                         "the set of off-grid angles changed between the "
                         "board and the placement file")
        self.assertGreater(len(shipped), 30)

    def test_no_part_was_turned_except_the_registered_ones(self):
        board = _board_numbers_and_angles()
        registry = Registry(_spec())
        for ref, shipped in self.angle.items():
            number, rotation = board[ref]
            turn = round((shipped - rotation) % 360.0, 4)
            want = round(registry.offset(number) % 360.0, 4)
            self.assertEqual(turn, want,
                             "{} was turned {} but its part is registered at "
                             "{}".format(ref, turn, want))


if __name__ == "__main__":
    unittest.main()
