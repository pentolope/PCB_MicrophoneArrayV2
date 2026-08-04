#!/usr/bin/env python3
"""KiCad-owned Specctra exchange and semantic board snapshots.

Run this script with the Python environment that can import KiCad 10's pcbnew
module. It never modifies the input board.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

try:
    import pcbnew  # type: ignore
except ImportError as exc:  # pragma: no cover - depends on KiCad runtime
    raise SystemExit(
        "pcbnew is unavailable. Run with KiCad's Python environment, not a "
        "generic Python interpreter."
    ) from exc


NM_PER_MM = 1_000_000.0


def mm(value: int | float) -> float:
    return round(float(value) / NM_PER_MM, 6)


def point(value: Any) -> list[float]:
    return [mm(value.x), mm(value.y)]


def orientation_degrees(item: Any) -> float:
    orientation = item.GetOrientation()
    if hasattr(orientation, "AsDegrees"):
        return round(float(orientation.AsDegrees()) % 360.0, 6)
    if hasattr(item, "GetOrientationDegrees"):
        return round(float(item.GetOrientationDegrees()) % 360.0, 6)
    return round(float(orientation) / 10.0 % 360.0, 6)


def layer_name(board: Any, layer_id: int) -> str:
    return str(board.GetLayerName(layer_id))


def pad_drill(pad: Any) -> list[float]:
    size = pad.GetDrillSize()
    return point(size)


def pad_size(pad: Any) -> list[float]:
    return point(pad.GetSize())


def footprint_snapshot(board: Any, footprint: Any) -> dict[str, Any]:
    pads = []
    for pad in footprint.Pads():
        pads.append(
            {
                "number": str(pad.GetNumber()),
                "position_mm": point(pad.GetPosition()),
                "orientation_deg": orientation_degrees(pad),
                "size_mm": pad_size(pad),
                "drill_mm": pad_drill(pad),
                "shape": int(pad.GetShape()),
                "attribute": int(pad.GetAttribute()),
                "net": str(pad.GetNetname()),
                "layers": str(
                    pad.GetLayerSet().FmtHex()
                    if hasattr(pad.GetLayerSet(), "FmtHex")
                    else pad.GetLayerSet()
                ),
            }
        )
    pads.sort(key=lambda row: (row["number"], row["position_mm"]))
    row: dict[str, Any] = {
        "reference": str(footprint.GetReference()),
        "value": str(footprint.GetValue()),
        "position_mm": point(footprint.GetPosition()),
        "orientation_deg": orientation_degrees(footprint),
        "side": "bottom"
        if layer_name(board, footprint.GetLayer()).startswith("B.")
        else "top",
        "pads": pads,
    }
    if hasattr(footprint, "GetFPID"):
        # KiCad 10's LIB_ID.Format() is no longer callable without arguments
        # from Python; GetFPIDAsString() is the supported accessor.
        row["footprint"] = str(footprint.GetFPIDAsString())
    if hasattr(footprint, "IsDNP"):
        row["dnp"] = bool(footprint.IsDNP())
    return row


def drawing_geometry(board: Any, item: Any) -> dict[str, Any] | None:
    if layer_name(board, item.GetLayer()) != "Edge.Cuts":
        return None
    row: dict[str, Any] = {"type": type(item).__name__}
    for key, getter in (
        ("start_mm", "GetStart"),
        ("end_mm", "GetEnd"),
        ("mid_mm", "GetMid"),
        ("center_mm", "GetCenter"),
    ):
        if hasattr(item, getter):
            try:
                row[key] = point(getattr(item, getter)())
            except Exception:
                pass
    if hasattr(item, "GetRadius"):
        try:
            row["radius_mm"] = mm(item.GetRadius())
        except Exception:
            pass
    return row


def board_snapshot(board_path: Path) -> dict[str, Any]:
    board = pcbnew.LoadBoard(str(board_path))
    footprints = [
        footprint_snapshot(board, footprint) for footprint in board.GetFootprints()
    ]
    footprints.sort(key=lambda row: row["reference"])

    outline = []
    for drawing in board.GetDrawings():
        row = drawing_geometry(board, drawing)
        if row:
            outline.append(row)
    outline.sort(key=lambda row: json.dumps(row, sort_keys=True))

    nets = []
    net_info = board.GetNetInfo()
    if hasattr(net_info, "NetsByName"):
        for name, net in net_info.NetsByName().items():
            nets.append({"name": str(name), "code": int(net.GetNetCode())})
    nets.sort(key=lambda row: row["name"])

    layers = []
    for layer_id in range(int(pcbnew.PCB_LAYER_ID_COUNT)):
        if board.IsLayerEnabled(layer_id):
            layers.append({"id": layer_id, "name": layer_name(board, layer_id)})

    origins: dict[str, list[float]] = {}
    design_settings = board.GetDesignSettings()
    for name, getter in (
        ("auxiliary", "GetAuxOrigin"),
        ("grid", "GetGridOrigin"),
    ):
        owner = design_settings if hasattr(design_settings, getter) else board
        if hasattr(owner, getter):
            origins[name] = point(getattr(owner, getter)())

    snapshot = {
        "schema": 1,
        "source": str(board_path.resolve()),
        "copper_layer_count": int(board.GetCopperLayerCount()),
        "enabled_layers": layers,
        "origins_mm": origins,
        "nets": nets,
        "footprints": footprints,
        "edge_cuts": outline,
    }
    semantic = {key: value for key, value in snapshot.items() if key != "source"}
    canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    snapshot["semantic_sha256"] = hashlib.sha256(canonical).hexdigest()
    return snapshot


def cmd_snapshot(args: argparse.Namespace) -> None:
    output = board_snapshot(Path(args.board))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Saved semantic snapshot: {target}")


def cmd_export(args: argparse.Namespace) -> None:
    board_path = Path(args.board)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    board = pcbnew.LoadBoard(str(board_path))
    ok = pcbnew.ExportSpecctraDSN(board, str(output))
    if ok is False or not output.is_file() or output.stat().st_size == 0:
        raise SystemExit("KiCad failed to export a non-empty Specctra DSN.")
    print(f"Exported Specctra DSN: {output}")


def cmd_import(args: argparse.Namespace) -> None:
    board_path = Path(args.board)
    session_path = Path(args.session)
    output = Path(args.output)
    if board_path.resolve() == output.resolve():
        raise SystemExit("Refusing to overwrite the input board.")
    output.parent.mkdir(parents=True, exist_ok=True)
    board = pcbnew.LoadBoard(str(board_path))
    ok = pcbnew.ImportSpecctraSES(board, str(session_path))
    if ok is False:
        raise SystemExit("KiCad reported a Specctra SES import failure.")
    if hasattr(board, "BuildConnectivity"):
        board.BuildConnectivity()
    if not pcbnew.SaveBoard(str(output), board):
        raise SystemExit("KiCad failed to save the imported board copy.")
    print(f"Imported Specctra SES into: {output}")


def cmd_compare(args: argparse.Namespace) -> None:
    before = board_snapshot(Path(args.before))
    after = board_snapshot(Path(args.after))
    keys = (
        "copper_layer_count",
        "enabled_layers",
        "origins_mm",
        "nets",
        "footprints",
        "edge_cuts",
    )
    changed = [key for key in keys if before[key] != after[key]]
    report = {
        "schema": 1,
        "before": str(Path(args.before).resolve()),
        "after": str(Path(args.after).resolve()),
        "invariants_equal": not changed,
        "changed_invariants": changed,
        "before_semantic_sha256": before["semantic_sha256"],
        "after_semantic_sha256": after["semantic_sha256"],
    }
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if changed:
        raise SystemExit(
            "SES import changed forbidden board invariants: " + ", ".join(changed)
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot", help="write a semantic board snapshot")
    snapshot.add_argument("board")
    snapshot.add_argument("output")
    snapshot.set_defaults(func=cmd_snapshot)

    export = sub.add_parser("export", help="export a Specctra DSN")
    export.add_argument("board")
    export.add_argument("output")
    export.set_defaults(func=cmd_export)

    import_ = sub.add_parser("import", help="import SES into a new board copy")
    import_.add_argument("board")
    import_.add_argument("session")
    import_.add_argument("output")
    import_.set_defaults(func=cmd_import)

    compare = sub.add_parser(
        "compare", help="compare invariants before and after SES import"
    )
    compare.add_argument("before")
    compare.add_argument("after")
    compare.add_argument("--output")
    compare.set_defaults(func=cmd_compare)
    return result


def main() -> int:
    args = parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
