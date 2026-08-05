"""Move GND stitching vias out of the via keep-out areas.

The signal nets are re-routed by KiCad Routing Tools, which obeys the keep-out
rule areas. The ground stitching vias predate that: they are placed by
tools/gen_pcb.py against its own clearance, and a handful land inside a
keep-out. Deleting them is not an option - they carry a pad to the plane, and
removing four of them left dangling ground tracks and four unconnected pads.

So they move. A stitching via connects one pad to a plane that is present
almost everywhere, so unlike a signal via it has real freedom: this walks
outward from the original position until the via is clear of every keep-out
and KiCad's DRC is no worse than it was, and drags any track endpoint sitting
on it.

    python tools/fix_keepout_vias.py BOARD --drc REPORT.json [--apply]
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

import pcbnew                                            # noqa: E402

MANIFEST = os.path.join(HERE, "verification", "boards", "live.json")
DIRECTIONS = 24
RADII_MM = [round(0.20 + 0.10 * i, 2) for i in range(12)]   # 0.2 .. 1.3


def offending_vias(report_path):
    """Via positions KiCad reports as inside a keep-out."""
    with open(report_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    found = []
    for violation in doc.get("violations", []):
        if violation.get("type") != "items_not_allowed":
            continue
        for item in violation.get("items", []):
            if item.get("description", "").startswith("Via"):
                pos = item.get("pos") or {}
                found.append((round(pos.get("x", 0.0), 4),
                              round(pos.get("y", 0.0), 4)))
    return found


def run_drc(board_path, workdir):
    out = os.path.join(workdir, "drc.json")
    cli = json.load(open(MANIFEST, encoding="utf-8"))["tools"]["kicad_cli"]
    subprocess.run(
        [cli, "pcb", "drc", "-o", out, "--format", "json", "--severity-all",
         "--severity-exclusions", "--all-track-errors", "--refill-zones",
         board_path], capture_output=True, text=True)
    if not os.path.isfile(out):
        raise RuntimeError("DRC produced no report")
    doc = json.load(open(out, encoding="utf-8"))
    counts = collections.Counter()
    for bucket in ("violations", "unconnected_items"):
        for item in doc.get(bucket, []):
            counts[item["type"]] += 1
    return counts


def move(board_path, target, new_x, new_y):
    board = pcbnew.LoadBoard(board_path)
    old = None
    for track in board.Tracks():
        if not isinstance(track, pcbnew.PCB_VIA):
            continue
        pos = track.GetPosition()
        if (round(pos.x / 1e6, 4), round(pos.y / 1e6, 4)) == target:
            old = pos
            track.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(new_x),
                                              pcbnew.FromMM(new_y)))
            break
    if old is None:
        return False
    new = pcbnew.VECTOR2I(pcbnew.FromMM(new_x), pcbnew.FromMM(new_y))
    for track in board.Tracks():
        if isinstance(track, pcbnew.PCB_VIA):
            continue
        if track.GetStart() == old:
            track.SetStart(new)
        if track.GetEnd() == old:
            track.SetEnd(new)
    board.Save(board_path)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("board")
    parser.add_argument("--drc", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    targets = offending_vias(args.drc)
    print("vias inside a keep-out: {}".format(len(targets)))
    for position in targets:
        print("  at {}".format(position))
    if not args.apply or not targets:
        return 0

    workdir = tempfile.mkdtemp(prefix="ko_")
    backup = os.path.join(workdir, "revert.kicad_pcb")
    try:
        baseline = run_drc(args.board, workdir)
        print("baseline: {} finding(s) {}".format(
            sum(baseline.values()), dict(baseline)))
        for target in targets:
            shutil.copy2(args.board, backup)
            placed = False
            for radius in RADII_MM:
                for step in range(DIRECTIONS):
                    angle = 2 * math.pi * step / DIRECTIONS
                    shutil.copy2(backup, args.board)
                    if not move(args.board, target,
                                target[0] + radius * math.cos(angle),
                                target[1] + radius * math.sin(angle)):
                        continue
                    after = run_drc(args.board, workdir)
                    if sum(after.values()) < sum(baseline.values()):
                        print("  moved via at {} by {:.2f} mm: {} -> {}".format(
                            target, radius, sum(baseline.values()),
                            sum(after.values())))
                        baseline = after
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                shutil.copy2(backup, args.board)
                print("  could not relocate the via at {}".format(target))
        print("final: {} finding(s) {}".format(
            sum(baseline.values()), dict(baseline)))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
