"""Move the vias that have somewhere to go, and prove each move with DRC.

Pairs the two halves of the problem: `via_relief_feasibility` finds a position
that satisfies the mask target and every copper, hole and drill clearance at
once, and this applies it - one via at a time, running KiCad's DRC after each,
keeping the move only if the board is exactly as clean as it was before.

Thirteen of the twenty-four overlapping vias have no such position within
0.8 mm. They are not touched, and they are listed at the end: they need either
local re-routing or a filled/capped via process, and neither is a decision a
script should take.

    python tools/apply_via_relief.py            # plan
    python tools/apply_via_relief.py --apply
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "verification"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import pcbnew                                            # noqa: E402

from pcbqa import geom                                   # noqa: E402
from pcbqa.core import Manifest                          # noqa: E402
from via_relief_feasibility import (                     # noqa: E402
    DIRECTIONS, RADII_MM, Index, board_rules, collect, feasible)

BOARD = os.path.join(HERE, "microphone_array_v2.kicad_pcb")
MANIFEST = os.path.join(HERE, "verification", "boards", "live.json")


def plan(board_path):
    manifest = Manifest(MANIFEST)
    profile = manifest.geometry_profile()
    geom.configure(profile.tolerance("polygon_chord_error_mm").value)
    target = manifest.get("via_mask.design_target_mm")

    board = pcbnew.LoadBoard(board_path)
    survey = geom.BoardGeometry(
        board, contact_tolerance_mm=profile.tolerance("contact_mm").value)
    rules = board_rules(board)
    apertures = [shape for side in ("front", "back")
                 for _entry, shape in survey.mask_openings(side)]
    index = Index(*collect(board, survey), apertures=apertures) \
        if False else Index(collect(board, survey)[0], apertures,
                            collect(board, survey)[1])

    movable, stuck = [], []
    for position, via in enumerate(survey.vias):
        worst = None
        for side in ("front", "back"):
            report = survey.via_mask_report(via, side)
            if report and report.get("annulus_to_opening_mm") is not None:
                gap = report["annulus_to_opening_mm"]
                if worst is None or gap < worst[0]:
                    worst = (gap, report)
        if worst is None or worst[0] > 0.0:
            continue
        found = None
        for radius in RADII_MM:
            for step in range(DIRECTIONS):
                angle = 2 * math.pi * step / DIRECTIONS
                x = via.x + radius * math.cos(angle)
                y = via.y + radius * math.sin(angle)
                if feasible(via, x, y, index, rules, target):
                    found = (x, y, radius, math.degrees(angle))
                    break
            if found:
                break
        record = {"index": position, "net": via.net,
                  "pad": worst[1].get("pad"), "found": found}
        (movable if found else stuck).append(record)
    return movable, stuck


def run_drc(board_path, workdir):
    out = os.path.join(workdir, "drc.json")
    cli = json.load(open(MANIFEST, encoding="utf-8"))["tools"]["kicad_cli"]
    subprocess.run(
        [cli, "pcb", "drc", "-o", out, "--format", "json", "--severity-all",
         "--severity-exclusions", "--all-track-errors", board_path],
        capture_output=True, text=True)
    if not os.path.isfile(out):
        raise RuntimeError("DRC produced no report")
    doc = json.load(open(out, encoding="utf-8"))
    counts = collections.Counter()
    for bucket in ("violations", "unconnected_items"):
        for item in doc.get(bucket, []):
            counts[item["type"]] += 1
    return counts


def move_via(board, index, new_x, new_y):
    vias = [t for t in board.Tracks() if isinstance(t, pcbnew.PCB_VIA)]
    tracks = [t for t in board.Tracks() if not isinstance(t, pcbnew.PCB_VIA)]
    via = vias[index]
    old = via.GetPosition()
    new = pcbnew.VECTOR2I(pcbnew.FromMM(new_x), pcbnew.FromMM(new_y))
    via.SetPosition(new)
    dragged = 0
    for track in tracks:
        if track.GetStart() == old:
            track.SetStart(new)
            dragged += 1
        if track.GetEnd() == old:
            track.SetEnd(new)
            dragged += 1
    return dragged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--board", default=BOARD)
    args = parser.parse_args()

    movable, stuck = plan(args.board)
    print("overlapping vias: {} ({} movable, {} boxed in)".format(
        len(movable) + len(stuck), len(movable), len(stuck)))
    for row in movable:
        _x, _y, radius, angle = row["found"]
        print("  move  net {:<14} pad {:<9} {:.2f} mm at {:.0f} deg".format(
            row["net"][:14], str(row["pad"]), radius, angle))
    if not args.apply:
        print("\nre-run with --apply")
        return 0

    workdir = tempfile.mkdtemp(prefix="relief_")
    backup = os.path.join(workdir, "revert.kicad_pcb")
    try:
        baseline = run_drc(args.board, workdir)
        print("\nbaseline DRC: {} finding(s) {}".format(
            sum(baseline.values()), dict(baseline)))
        kept, rejected = [], []
        for row in movable:
            shutil.copy2(args.board, backup)
            board = pcbnew.LoadBoard(args.board)
            x, y, radius, angle = row["found"]
            dragged = move_via(board, row["index"], x, y)
            board.Save(args.board)
            after = run_drc(args.board, workdir)
            if after == baseline:
                kept.append(row)
                print("  kept   net {:<14} pad {:<9} ({} endpoint(s) dragged)"
                      .format(row["net"][:14], str(row["pad"]), dragged))
            else:
                shutil.copy2(backup, args.board)
                rejected.append((row, dict(after - baseline)))
                print("  backed out net {:<12} pad {:<9}: {}".format(
                    row["net"][:12], str(row["pad"]), dict(after - baseline)))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("\nmoved {}, backed out {}, left boxed-in {}".format(
        len(kept), len(rejected), len(stuck)))
    if stuck:
        print("\nno position exists for these; they need re-routing or a "
              "filled/capped via process:")
        for row in stuck:
            print("  net {:<14} pad {}".format(row["net"][:14], row["pad"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
