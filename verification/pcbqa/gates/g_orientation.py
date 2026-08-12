"""Is every placement angle in the frame the assembly machine works in?

A placement file carries an angle per part, and two different things can be
wrong with it. The angle can be written in a range the fab does not expect -
KiCad uses (-180, 180], the fab reads [0, 360) - which is the same orientation
said differently and costs an engineering query. Or the part's zero
orientation in the fab's library can differ from the footprint's zero in
KiCad, which is not a matter of expression at all: every instance of that part
gets fitted turned by the difference.

This gate checks both against the board, and it checks the thing that is
easiest to get wrong: that the two are not confused for one another. An offset
invented to make a negative angle positive turns a part that was right.
"""

from __future__ import annotations

import csv
import os

from ..core import gate

TOLERANCE_DEG = 1e-6


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _part_numbers(ctx, field_name):
    """Each reference's distributor part number, from the native board."""
    board = ctx.board()
    out = {}
    for footprint in board.Footprints():
        for field in footprint.GetFields():
            if field.GetName() == field_name and field.GetText().strip():
                out[footprint.GetReference()] = field.GetText().strip()
    return out


def _native_rotation(ctx):
    board = ctx.board()
    return {fp.GetReference(): fp.GetOrientationDegrees()
            for fp in board.Footprints()}


@gate("CPL.ORIENTATION", "Placement angles are normalised and library-zero corrected",
      requires=("artifacts.cpl", "artifacts.cpl_fields",
                "release_generation.cpl_orientation"))
def cpl_orientation(ctx, res):
    spec = ctx.manifest.get("release_generation.cpl_orientation")
    path = ctx.manifest.resolve(ctx.manifest.get("artifacts.cpl"))
    if not os.path.isfile(path):
        return res.errored("packaged CPL not found: " + path)
    res.evidence_file(path)
    fields = ctx.manifest.get("artifacts.cpl_fields")
    low, high = res.limit(ctx.manifest.constraint(
        "release_generation.cpl_orientation.normalize_range_deg",
        units="degrees",
        cid="cpl_orientation.normalize_range_deg")).value
    span = high - low

    parts = spec.get("parts", [])
    offsets, declared_rows = {}, {}
    problems = []
    for row in parts:
        lcsc = row["lcsc"]
        if lcsc in offsets and offsets[lcsc] != float(row["offset_deg"]):
            problems.append({
                "lcsc": lcsc,
                "issue": "the same part is declared with two different offsets",
                "values": [offsets[lcsc], float(row["offset_deg"])]})
        offsets[lcsc] = float(row["offset_deg"])
        declared_rows[lcsc] = row

    lcsc_of = _part_numbers(ctx, spec.get("part_number_field", "MPN"))
    native = _native_rotation(ctx)
    rows = _read(path)
    res.measurements["placements"] = len(rows)
    res.measurements["declared_offsets"] = {
        k: v for k, v in sorted(offsets.items())}

    seen_by_lcsc = {}
    outside, wrong, unknown = [], [], []
    for row in rows:
        ref = row.get(fields["designator"], "")
        try:
            shipped = float(row.get(fields["rotation"], ""))
        except ValueError:
            problems.append({"reference": ref,
                             "issue": "rotation is not a number",
                             "value": row.get(fields["rotation"])})
            continue
        if not (low - TOLERANCE_DEG <= shipped < high + TOLERANCE_DEG):
            outside.append({"reference": ref, "rotation": shipped,
                            "issue": "rotation is outside [{}, {})".format(
                                low, high)})
        lcsc = lcsc_of.get(ref)
        if lcsc is None:
            unknown.append(ref)
            continue
        if ref not in native:
            problems.append({"reference": ref,
                             "issue": "shipped in the CPL but not on the board"})
            continue
        offset = offsets.get(lcsc, 0.0)
        expected = low + (native[ref] + offset - low) % span
        if abs(((shipped - expected + 180.0) % 360.0) - 180.0) > 1e-3:
            wrong.append({"reference": ref, "lcsc": lcsc,
                          "board_rotation": round(native[ref], 4),
                          "declared_offset": offset,
                          "expected": round(expected, 4),
                          "shipped": shipped,
                          "issue": "shipped angle is not the board angle plus "
                                   "the declared offset, normalised"})
        seen_by_lcsc.setdefault(lcsc, []).append((ref, shipped, native[ref]))

    # A part with an offset must take it everywhere it appears. Two placements
    # of one part that disagree mean the table was applied by reference rather
    # than by part, which is how U3 gets turned and U4 does not.
    for lcsc, entries in sorted(seen_by_lcsc.items()):
        deltas = {round(((s - n) % 360.0), 4) for _r, s, n in entries}
        if len(deltas) > 1:
            problems.append({
                "lcsc": lcsc,
                "issue": "instances of one part were corrected differently",
                "references": [r for r, _s, _n in entries],
                "corrections_seen": sorted(deltas)})

    # An offset declared for a part that is not on this board is dead weight
    # that will be read as authoritative by the next person.
    on_board = set(lcsc_of.values())
    for lcsc in sorted(offsets):
        if lcsc not in on_board:
            problems.append({"lcsc": lcsc,
                             "issue": "an offset is declared for a part this "
                                      "board does not carry"})

    for row in parts:
        for required in ("mpn", "package", "kicad_footprint", "evidence"):
            if not str(row.get(required, "")).strip():
                problems.append({
                    "lcsc": row.get("lcsc"),
                    "issue": "the offset records no {}; an orientation "
                             "correction nobody can check is a guess".format(
                                 required)})

    problems.extend(outside)
    problems.extend(wrong)
    if unknown:
        problems.append({"issue": "no part number on the board for these "
                                  "placements, so no offset could be checked",
                         "references": sorted(unknown)[:20]})

    res.measurements["turned_by_offset"] = sorted(
        ref for ref in lcsc_of if offsets.get(lcsc_of[ref]))
    for problem in problems[:40]:
        res.finding(**problem)
    if problems:
        return res.failed("{} placement-orientation problem(s)".format(
            len(problems)))
    return res.passed(
        "all {} placements lie in [{}, {}) and match the board angle plus the "
        "offset declared for their part; {} part(s) carry an offset".format(
            len(rows), low, high, len(offsets)))
