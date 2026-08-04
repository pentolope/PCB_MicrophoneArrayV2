"""Assembly-data parity: the packaged BOM and CPL against the native design.

Authoritative data is derived from the native KiCad schematic (via kicad-cli's
netlist export, which carries symbol fields) joined to the native PCB (which
carries placement and population state). The packaged BOM and CPL are then
compared item by item. Comparing only the PCB against the CPL - as the previous
implementation did - never opens the BOM at all, so a corrupted part number or
a missing line could not be seen.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter

from ..core import gate, sha256_file


def _native_assembly(ctx):
    """{ref: {...}} for every part the native design says is populated."""
    def build():
        import pcbnew
        board = ctx.board()
        fields = ctx.manifest.get("assembly.schematic_fields")
        parts = {}
        for fp in board.Footprints():
            ref = fp.GetReference()
            pos = fp.GetPosition()
            populated = not (fp.IsDNP() or fp.IsExcludedFromBOM())
            entry = {
                "reference": ref,
                "value": fp.GetValue(),
                "footprint": fp.GetFPIDAsString(),
                "populated": populated,
                "dnp": bool(fp.IsDNP()),
                "excluded_from_bom": bool(fp.IsExcludedFromBOM()),
                "side": "Bottom" if fp.IsFlipped() else "Top",
                "x_mm": round(pos.x / 1e6, 4),
                "y_mm": round(-pos.y / 1e6, 4),
                "rotation_deg": round(fp.GetOrientationDegrees() % 360.0, 4),
                "schematic_fields": {},
            }
            for name in fields:
                try:
                    if fp.HasField(name):
                        entry["schematic_fields"][name] = fp.GetFieldText(name)
                except Exception:
                    pass
            parts[ref] = entry
        return parts
    return ctx.cache("native_assembly", build)


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


@gate("BOM.NATIVE_PARITY", "Packaged BOM matches the native design",
      requires=("artifacts.bom", "assembly.bom_fields"))
def bom_parity(ctx, res):
    path = ctx.manifest.resolve(ctx.manifest.get("artifacts.bom"))
    if not os.path.isfile(path):
        return res.errored(f"packaged BOM not found: {path}")
    res.evidence_file(path)
    fields = ctx.manifest.get("assembly.bom_fields")
    required = res.limit(ctx.manifest.constraint(
        "assembly.required_part_fields", units="field name",
        cid="assembly.required_part_fields")).value

    native = _native_assembly(ctx)
    expected = {r: e for r, e in native.items() if e["populated"]}
    rows = _read_csv(path)
    res.measurements["bom_lines"] = len(rows)
    res.measurements["native_populated"] = len(expected)

    problems = []
    seen = Counter()
    packaged = {}
    for index, row in enumerate(rows, start=2):
        refs = [r.strip() for r in (row.get(fields["designators"]) or "").split(",")
                if r.strip()]
        if not refs:
            problems.append({"line": index, "issue": "BOM line names no designator"})
            continue
        try:
            quantity = int(float(row.get(fields["quantity"]) or 0))
        except ValueError:
            quantity = None
        if quantity is not None and quantity != len(refs):
            problems.append({"line": index, "issue": "quantity does not match the "
                                                     "designator list",
                             "quantity": quantity, "designators": len(refs)})
        for ref in refs:
            seen[ref] += 1
            packaged[ref] = {"line": index, "row": row}

    for ref, count in seen.items():
        if count > 1:
            problems.append({"reference": ref, "issue": "designator appears on more "
                                                        "than one BOM line",
                             "count": count})
    for ref in sorted(set(expected) - set(packaged)):
        problems.append({"reference": ref,
                         "issue": "populated on the board but missing from the BOM"})
    for ref in sorted(set(packaged) - set(expected)):
        state = native.get(ref)
        problems.append({"reference": ref,
                         "issue": "in the BOM but not populated on the board",
                         "dnp": state["dnp"] if state else None,
                         "excluded_from_bom": state["excluded_from_bom"] if state else None})

    for ref in sorted(set(expected) & set(packaged)):
        want, row = expected[ref], packaged[ref]["row"]
        line = packaged[ref]["line"]
        got_value = (row.get(fields["value"]) or "").strip()
        if got_value != want["value"]:
            problems.append({"reference": ref, "line": line, "issue": "value mismatch",
                             "native": want["value"], "packaged": got_value})
        got_fp = (row.get(fields["footprint"]) or "").strip()
        if got_fp and got_fp not in want["footprint"]:
            problems.append({"reference": ref, "line": line,
                             "issue": "footprint mismatch",
                             "native": want["footprint"], "packaged": got_fp})
        for field_name in required:
            column = fields.get(field_name)
            if column is None:
                continue
            got = (row.get(column) or "").strip()
            expect = (want["schematic_fields"].get(field_name) or "").strip()
            if not got:
                problems.append({"reference": ref, "line": line,
                                 "issue": f"required part field {field_name!r} is empty"})
            elif expect and got != expect:
                problems.append({"reference": ref, "line": line,
                                 "issue": f"{field_name} disagrees with the design",
                                 "native": expect, "packaged": got})
    for p in problems[:80]:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} BOM disagreement(s) with the native design")
    return res.passed(f"all {len(expected)} populated parts agree between the native "
                      f"design and the packaged BOM")


@gate("CPL.NATIVE_PARITY", "Packaged CPL matches the native board",
      requires=("artifacts.cpl", "artifacts.cpl_fields"))
def cpl_parity(ctx, res):
    path = ctx.manifest.resolve(ctx.manifest.get("artifacts.cpl"))
    if not os.path.isfile(path):
        return res.errored(f"packaged CPL not found: {path}")
    res.evidence_file(path)
    fields = ctx.manifest.get("artifacts.cpl_fields")
    tol = res.limit(ctx.manifest.constraint(
        "artifacts.position_tolerance_mm", units="mm",
        cid="artifacts.position_tolerance_mm")).value
    rot_tol = res.limit(ctx.manifest.geometry_profile()
                        .tolerance("rotation_match_deg")).value
    origin = res.limit(ctx.manifest.constraint(
        "artifacts.cpl_origin", units="frame", cid="artifacts.cpl_origin")).value

    native = _native_assembly(ctx)
    expected = {r: e for r, e in native.items() if e["populated"]}
    rows = {r[fields["designator"]].strip(): r for r in _read_csv(path)}
    res.measurements["cpl_rows"] = len(rows)
    res.measurements["native_populated"] = len(expected)
    res.measurements["coordinate_frame"] = origin

    dx, dy = origin.get("offset_mm", [0.0, 0.0])
    problems = []
    for ref in sorted(set(expected) | set(rows)):
        if ref not in rows:
            problems.append({"reference": ref, "issue": "populated but absent from CPL"})
            continue
        if ref not in expected:
            problems.append({"reference": ref, "issue": "in CPL but not populated"})
            continue
        want, row = expected[ref], rows[ref]
        if row[fields["side"]].strip().lower() != want["side"].lower():
            problems.append({"reference": ref, "issue": "side mismatch",
                             "native": want["side"], "packaged": row[fields["side"]]})
        for key, axis, shift in (("x", "x_mm", dx), ("y", "y_mm", dy)):
            try:
                got = float(row[fields[key]])
            except (KeyError, ValueError):
                problems.append({"reference": ref, "issue": f"unparseable {key}"})
                continue
            delta = abs(got - (want[axis] + shift))
            if delta > tol:
                problems.append({"reference": ref, "issue": f"{key} mismatch",
                                 "native_mm": want[axis], "packaged": got,
                                 "delta_mm": round(delta, 4)})
        try:
            got = float(row[fields["rotation"]]) % 360.0
            if abs(((got - want["rotation_deg"] + 180) % 360) - 180) > rot_tol:
                problems.append({"reference": ref, "issue": "rotation mismatch",
                                 "native_deg": want["rotation_deg"], "packaged": got})
        except (KeyError, ValueError):
            problems.append({"reference": ref, "issue": "unparseable rotation"})
    for p in problems[:80]:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} CPL disagreement(s) with the native board")
    return res.passed(f"all {len(expected)} populated parts agree between the native "
                      f"board and the packaged CPL")
