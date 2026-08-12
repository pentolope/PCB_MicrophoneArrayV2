"""Is every placement angle one a reviewed part number vouches for?

A placement file carries an angle per part, and two different things can be
wrong with it. The angle can be written in a range the assembly house does not
expect - the layout tool uses (-180, 180], the house reads [0, 360) - which is
the same orientation said differently and costs an engineering query. Or the
part's zero orientation in the house's library can differ from the footprint's
zero in the layout, which is not a matter of expression at all: every instance
of that part is fitted turned by the difference.

Checking the shipped file against the registry the generator used would prove
only that a program can apply its own table twice. So this gate does three
separate things instead:

  * it re-derives every offset from the frozen library evidence and requires
    the registry to agree, which is what makes the registry authoritative
    rather than self-asserted;
  * it checks coverage against the populated BOM and the board's own
    footprints, so a part that is about to be fitted cannot simply be absent
    from the registry;
  * it recomputes each shipped angle from the board and the registry.

References sharing a part number must also share a correction. That is the
failure keying by reference invites - one of a pair turned and the other not -
and it is checked from the shipped file rather than from the table.
"""

from __future__ import annotations

import csv
import json
import os

from ..core import gate
from ..orientation import Registry

TOLERANCE_DEG = 1e-6
ANGLE_MATCH_DEG = 1e-3


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _board_parts(ctx, field_name):
    """{ref: (part number, rotation)} from the native board."""
    out = {}
    for footprint in ctx.board().Footprints():
        number = ""
        for field in footprint.GetFields():
            if field.GetName() == field_name and field.GetText().strip():
                number = field.GetText().strip()
        out[footprint.GetReference()] = (number,
                                         footprint.GetOrientationDegrees())
    return out


def _bom_references(ctx):
    """Every reference the packaged BOM says will be fitted."""
    path = ctx.manifest.resolve(ctx.manifest.get("artifacts.bom"))
    if not os.path.isfile(path):
        return None
    fields = ctx.manifest.get("assembly.bom_fields")
    refs = set()
    for row in _read(path):
        for ref in (row.get(fields["designators"]) or "").split(","):
            if ref.strip():
                refs.add(ref.strip())
    return refs


def _rederive(ctx, spec):
    """Score the frozen library evidence again, independently of the registry.

    Returns {lcsc: {...}} or None when the scoring tool is unavailable, which
    is reported rather than passed over: an unverifiable registry is the thing
    this gate exists to prevent.
    """
    import sys
    tools = ctx.manifest.resolve("tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    # A clean run inventories the copied project and then holds it to that
    # inventory exactly. Importing from inside it must not leave a __pycache__
    # behind, or reading the evidence would itself be the thing that fails.
    was_writing = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        import jlc_orientation
    except ImportError:
        return None
    finally:
        sys.dont_write_bytecode = was_writing
    jlc_orientation.HERE = ctx.manifest.resolve(".")
    jlc_orientation.FIXTURES = ctx.manifest.resolve(
        spec["evidence"]["fixtures"].rsplit("/", 1)[0])
    jlc_orientation.BOARD = ctx.manifest.resolve(
        ctx.manifest.get("sources.pcb"))
    return jlc_orientation.derive(spec.get("part_number_field", "MPN"),
                                  jlc_orientation.BOARD)


@gate("CPL.ORIENTATION",
      "Placement angles come from a reviewed, evidence-backed registry",
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
        units="degrees", cid="cpl_orientation.normalize_range_deg")).value

    registry = Registry(spec)
    problems = list(registry.defects())
    res.measurements["reviewed_parts"] = len(registry.entries)
    res.measurements["reviewed_offsets"] = {
        lcsc: float(row["offset_deg"])
        for lcsc, row in sorted(registry.entries.items())}

    board = _board_parts(ctx, registry.part_number_field)
    rows = _read(path)
    res.measurements["placements"] = len(rows)

    # 1. the registry says what the frozen library evidence says
    derived = _rederive(ctx, spec)
    if derived is None:
        problems.append({"issue": "the orientation evidence could not be "
                                  "re-derived, so the registry cannot be "
                                  "confirmed against anything"})
    else:
        checked = 0
        for lcsc, row in sorted(registry.entries.items()):
            evidence = derived.get(lcsc)
            if evidence is None or "error" in evidence:
                problems.append({
                    "lcsc": lcsc,
                    "issue": "the registry declares an offset with no frozen "
                             "library evidence behind it"})
                continue
            if not evidence.get("decisive"):
                problems.append({
                    "lcsc": lcsc,
                    "issue": "the evidence does not decide an offset",
                    "best_worst_deg": evidence["best_worst_deg"],
                    "margin_deg": evidence["margin_deg"]})
            declared = float(row["offset_deg"])
            got = float(evidence["best_offset_deg"])
            if abs(((declared - got + 180.0) % 360.0) - 180.0) > 1.0:
                problems.append({
                    "lcsc": lcsc, "issue": "the registry disagrees with the "
                                           "library evidence",
                    "registry_deg": declared, "evidence_deg": got})
            recorded = str(row.get("evidence_sha256", "")).strip()
            if recorded and recorded != evidence["evidence_sha256"]:
                problems.append({
                    "lcsc": lcsc,
                    "issue": "the evidence digest recorded in the registry is "
                             "not the digest of the evidence on disk"})
            checked += 1
        res.measurements["offsets_rederived_from_evidence"] = checked

    # 2. coverage, judged against the board and the packaged BOM rather than
    #    against the registry's own idea of what exists
    placed = {row.get(fields["designator"], "").strip() for row in rows}
    bom = _bom_references(ctx)
    res.measurements["bom_references"] = len(bom) if bom is not None else None
    to_be_fitted = set(placed) | (bom or set())
    uncovered, unnumbered = [], []
    for ref in sorted(to_be_fitted):
        number, _rot = board.get(ref, ("", None))
        if not number:
            unnumbered.append(ref)
        elif not registry.covers(number):
            uncovered.append({"reference": ref, "lcsc": number})
    if unnumbered:
        problems.append({
            "issue": "these parts are to be fitted but carry no part number "
                     "on the board, so no reviewed orientation can apply",
            "references": unnumbered[:20]})
    for entry in uncovered[:20]:
        problems.append({**entry,
                         "issue": "to be fitted but absent from the reviewed "
                                  "orientation registry"})
    if bom is not None:
        only_in_bom = sorted(bom - placed)
        if only_in_bom:
            problems.append({"issue": "on the BOM but absent from the "
                                      "placement file",
                             "references": only_in_bom[:20]})

    # 3. every shipped angle, recomputed from the board and the registry
    outside, wrong, by_part = [], [], {}
    for row in rows:
        ref = row.get(fields["designator"], "").strip()
        try:
            shipped = float(row.get(fields["rotation"], ""))
        except (TypeError, ValueError):
            problems.append({"reference": ref,
                             "issue": "rotation is not a number",
                             "value": row.get(fields["rotation"])})
            continue
        if not (low - TOLERANCE_DEG <= shipped < high + TOLERANCE_DEG):
            outside.append({"reference": ref, "rotation": shipped,
                            "issue": "rotation is outside [{}, {})".format(
                                low, high)})
        number, rotation = board.get(ref, ("", None))
        if rotation is None:
            problems.append({"reference": ref,
                             "issue": "shipped in the placement file but not "
                                      "on the board"})
            continue
        if not registry.covers(number):
            continue                     # already reported as uncovered
        want = registry.angle_for(number, rotation)
        if abs(((shipped - want + 180.0) % 360.0) - 180.0) > ANGLE_MATCH_DEG:
            wrong.append({"reference": ref, "lcsc": number,
                          "board_deg": round(rotation, 4),
                          "reviewed_offset_deg": registry.offset(number),
                          "expected_deg": round(want, 4),
                          "shipped_deg": shipped,
                          "issue": "shipped angle is not the board angle plus "
                                   "the reviewed offset, normalised"})
        by_part.setdefault(number, []).append((ref, shipped, rotation))

    # 4. one part, one correction - checked from the shipped file
    for number, entries in sorted(by_part.items()):
        turns = {round((s - r) % 360.0, 4) for _ref, s, r in entries}
        if len(turns) > 1:
            problems.append({
                "lcsc": number,
                "issue": "instances of one part were corrected differently",
                "references": sorted(ref for ref, _s, _r in entries),
                "corrections_seen": sorted(turns)})

    problems.extend(outside)
    problems.extend(wrong)
    res.measurements["parts_with_offset"] = sorted(
        lcsc for lcsc, row in registry.entries.items()
        if float(row["offset_deg"]))
    res.measurements["references_turned"] = sorted(
        ref for ref in placed
        if registry.covers(board.get(ref, ("", None))[0])
        and registry.offset(board[ref][0]))

    for problem in problems[:40]:
        res.finding(**problem)
    if problems:
        return res.failed("{} placement-orientation problem(s)".format(
            len(problems)))
    return res.passed(
        "{} placements in [{}, {}); every one from a reviewed part entry, and "
        "all {} entries re-derived from the frozen library evidence".format(
            len(rows), low, high, len(registry.entries)))
