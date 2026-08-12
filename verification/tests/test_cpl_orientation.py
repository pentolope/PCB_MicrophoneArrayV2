"""Placement-orientation handling: normalisation, offsets, and the gate.

The two corrections a placement angle needs are easy to confuse, and confusing
them is expensive. Normalisation moves an angle into the range the fab reads
and changes no orientation. A library-zero offset does change orientation, and
only for parts whose zero in the fab's library differs from the footprint's
zero in KiCad. An offset invented to make a negative angle positive turns a
part that was already right; a missing offset ships a part turned.

These drive the gate against the packaged CPL and against copies broken in
each of the specific ways that have actually happened on this board.
"""

from __future__ import annotations

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

LIVE = os.path.join(HERE, "boards", "live.json")
GATE = "CPL.ORIENTATION"
PROJECT = os.path.abspath(os.path.join(HERE, ".."))


def _policy():
    with open(LIVE, encoding="utf-8") as fh:
        return json.load(fh)["release_generation"]["cpl_orientation"]


def _run(manifest_path):
    """Run only the orientation gate, so a broken copy needs no other file."""
    ctx = Context(Manifest(manifest_path),
                  tempfile.mkdtemp(prefix="pcbqa_orient_work_"))
    results = core.run_all(ctx, only={GATE})
    return {r.gate_id: r.to_dict() for r in results}[GATE]


def _copy_with_cpl(edit):
    """A minimal project copy whose CPL has been altered, and the gate on it.

    Only the files this gate reads are copied - the board and the placement
    file - so a mutation costs a few milliseconds rather than duplicating the
    renders and the fabrication archive.
    """
    work = tempfile.mkdtemp(prefix="pcbqa_orient_")
    project = os.path.join(work, "project")
    os.makedirs(os.path.join(project, "generated", "release"))
    for name in ("microphone_array_v2.kicad_pcb", "microphone_array_v2.kicad_sch",
                 "microphone_array_v2.kicad_pro"):
        shutil.copy2(os.path.join(PROJECT, name), project)
    source = os.path.join(PROJECT, "generated", "release", "cpl.csv")
    target = os.path.join(project, "generated", "release", "cpl.csv")
    with open(source, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows, names = list(reader), list(reader.fieldnames)
    edit(rows)
    with open(target, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)

    with open(LIVE, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["project_root"] = project
    doc["fixture"] = {"attributes_file": os.path.join(PROJECT, ".gitattributes")}
    path = os.path.join(work, "manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return _run(path)


class OrientationPolicy(unittest.TestCase):
    """What the manifest declares, judged on its own terms."""

    def setUp(self):
        self.spec = _policy()
        self.parts = self.spec["parts"]

    def test_normalisation_is_the_full_turn(self):
        self.assertEqual(list(self.spec["normalize_range_deg"]), [0, 360])

    def test_one_part_number_one_offset(self):
        seen = {}
        for row in self.parts:
            if row["lcsc"] in seen:
                self.assertEqual(seen[row["lcsc"]], row["offset_deg"],
                                 "{} declared twice with different offsets"
                                 .format(row["lcsc"]))
            seen[row["lcsc"]] = row["offset_deg"]

    def test_no_offset_is_a_disguised_normalisation(self):
        """A whole-turn offset changes nothing and hides a normalisation bug."""
        for row in self.parts:
            self.assertNotEqual(float(row["offset_deg"]) % 360.0, 0.0,
                                "{} declares an offset of a whole turn"
                                .format(row["lcsc"]))

    def test_every_offset_carries_its_evidence(self):
        for row in self.parts:
            for field in ("mpn", "package", "kicad_footprint", "evidence"):
                self.assertTrue(str(row.get(field, "")).strip(),
                                "{} records no {}".format(row["lcsc"], field))
            self.assertGreater(len(row["evidence"]), 80,
                               "{}'s evidence is too thin to check"
                               .format(row["lcsc"]))

    def test_the_two_esd_arrays_cannot_diverge(self):
        """U3 and U4 are one part, so keying by LCSC settles it mechanically."""
        import pcbnew
        board = pcbnew.LoadBoard(
            os.path.join(PROJECT, "microphone_array_v2.kicad_pcb"))
        lcsc = {}
        for fp in board.Footprints():
            for field in fp.GetFields():
                if field.GetName() == "LCSC":
                    lcsc[fp.GetReference()] = field.GetText().strip()
        self.assertEqual(lcsc.get("U3"), lcsc.get("U4"))
        self.assertIn(lcsc.get("U3"), {r["lcsc"] for r in self.parts})


class ShippedCplIsOriented(unittest.TestCase):
    """The gate, against the packaged CPL and against broken copies."""

    def test_the_shipped_cpl_passes(self):
        gate = _run(LIVE)
        self.assertEqual(gate["status"], Status.PASS, gate.get("findings"))

    def test_every_shipped_angle_is_in_range(self):
        path = os.path.join(PROJECT, "generated", "release", "cpl.csv")
        with open(path, newline="", encoding="utf-8") as fh:
            angles = [float(r["Rotation"]) for r in csv.DictReader(fh)]
        self.assertTrue(angles)
        for angle in angles:
            self.assertGreaterEqual(angle, 0.0)
            self.assertLess(angle, 360.0)

    def test_an_unnormalised_angle_is_caught(self):
        """The original defect: KiCad's (-180, 180] shipped unchanged."""
        def edit(rows):
            for row in rows:
                if row["Designator"] == "MK1":
                    row["Rotation"] = "-90.000000"
        gate = _copy_with_cpl(edit)
        self.assertEqual(gate["status"], Status.FAIL)
        self.assertTrue(any("outside" in f.get("issue", "")
                            for f in gate["findings"]), gate["findings"])

    def test_a_missing_library_offset_is_caught(self):
        """U2 shipped at the board angle, as if its library zero matched."""
        def edit(rows):
            for row in rows:
                if row["Designator"] == "U2":
                    row["Rotation"] = "0.000000"
        gate = _copy_with_cpl(edit)
        self.assertEqual(gate["status"], Status.FAIL)
        self.assertTrue(any(f.get("reference") == "U2"
                            for f in gate["findings"]), gate["findings"])

    def test_one_part_turned_two_ways_is_caught(self):
        """U3 corrected and U4 not - the failure keying by reference invites."""
        def edit(rows):
            for row in rows:
                if row["Designator"] == "U4":
                    row["Rotation"] = "0.000000"
        gate = _copy_with_cpl(edit)
        self.assertEqual(gate["status"], Status.FAIL)
        self.assertTrue(
            any("corrected differently" in f.get("issue", "")
                or f.get("reference") == "U4" for f in gate["findings"]),
            gate["findings"])

    def test_a_passive_given_an_offset_is_caught(self):
        """Turning a part that was right is as bad as not turning one."""
        def edit(rows):
            for row in rows:
                if row["Designator"] == "CB1":
                    row["Rotation"] = "213.750000"      # 33.75 + 180
        gate = _copy_with_cpl(edit)
        self.assertEqual(gate["status"], Status.FAIL)
        self.assertTrue(any(f.get("reference") == "CB1"
                            for f in gate["findings"]), gate["findings"])


if __name__ == "__main__":
    unittest.main()
