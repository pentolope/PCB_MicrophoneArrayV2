"""Move vias off the solder-mask openings they overlap, one verified step at a time.

Every via on this board is already tented, which is the right default. Tenting
only helps where the mask actually covers the barrel, and it does not where a
via's annulus runs into a pad's mask aperture: the aperture wins, the barrel is
open, and if that pad also receives paste the solder wicks out of the joint and
down the hole. Twenty-four vias overlap an aperture; thirteen of those sit on a
pad that gets paste.

An earlier version of this script computed all the displacements up front and
applied them together, checking only pad copper for collisions. It produced a
board with a hundred DRC violations - clearance, hole clearance and shorts it
had no model for. So this version does not have a clearance model at all. It
moves one via, asks KiCad, and keeps the move only if the board is still as
clean as it was before. That is slower by a few minutes and it cannot be wrong
in the same way.

    python tools/relieve_vias.py --report            # what would move, and why
    python tools/relieve_vias.py --apply             # guarded, one via at a time
    python tools/relieve_vias.py --apply --all       # every via under target
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
from shapely.geometry import Point                       # noqa: E402
from shapely.ops import nearest_points                   # noqa: E402

from pcbqa import geom                                   # noqa: E402
from pcbqa.core import Manifest                          # noqa: E402

BOARD = os.path.join(HERE, "microphone_array_v2.kicad_pcb")
MANIFEST = os.path.join(HERE, "verification", "boards", "live.json")

MARGIN_MM = 0.02
MAX_TRAVEL_MM = 0.75
# Tried in order: the smallest step that clears the target first, then longer
# ones, because a shorter move disturbs the routing less.
STEP_SCALE = (1.0, 1.35, 1.75, 2.25)


def load(board_path):
    manifest = Manifest(MANIFEST)
    profile = manifest.geometry_profile()
    geom.configure(profile.tolerance("polygon_chord_error_mm").value)
    board = pcbnew.LoadBoard(board_path)
    survey = geom.BoardGeometry(
        board, contact_tolerance_mm=profile.tolerance("contact_mm").value)
    return manifest, board, survey


def worst_opening(survey, via):
    worst = None
    for side in ("front", "back"):
        report = survey.via_mask_report(via, side)
        if not report:
            continue
        gap = report.get("annulus_to_opening_mm")
        if gap is None:
            continue
        if worst is None or gap < worst[1]:
            worst = (side, gap, report)
    return worst


def pad_entry(survey, label):
    for entry in survey.pads:
        if entry["label"] == label:
            return entry
    return None


def receives_paste(entry):
    """A pad with a paste aperture is a pad solder can leave through."""
    if entry is None:
        return False
    pad = entry.get("pad_obj")
    if pad is None:
        return False
    try:
        layers = pad.GetLayerSet()
        return bool(layers.Contains(pcbnew.F_Paste)
                    or layers.Contains(pcbnew.B_Paste))
    except Exception:                                    # noqa: BLE001
        return False


def push_direction(survey, via, side, label):
    shape = None
    for entry, opening in survey.mask_openings(side):
        if entry["label"] == label:
            shape = opening
            break
    if shape is None:
        return None
    centre = Point(via.x, via.y)
    near_opening, _ = nearest_points(shape, centre)
    dx, dy = via.x - near_opening.x, via.y - near_opening.y
    length = math.hypot(dx, dy)
    if length < 1e-9:
        dx, dy = via.x - shape.centroid.x, via.y - shape.centroid.y
        length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return dx / length, dy / length


def candidates(survey, manifest, everything=False):
    target = manifest.get("via_mask.design_target_mm")
    rows = []
    for index, via in enumerate(survey.vias):
        worst = worst_opening(survey, via)
        if worst is None:
            continue
        side, gap, report = worst
        if gap >= target:
            continue
        entry = pad_entry(survey, report.get("pad"))
        paste = receives_paste(entry)
        overlaps = gap <= 0.0
        if not everything and not overlaps:
            continue
        direction = push_direction(survey, via, side, report.get("pad"))
        if direction is None:
            continue
        rows.append({
            "index": index, "x": via.x, "y": via.y, "net": via.net,
            "gap": gap, "pad": report.get("pad"),
            "pad_net": report.get("pad_net"), "paste": paste,
            "overlaps": overlaps,
            "travel": (target - gap) + MARGIN_MM,
            "dx": direction[0], "dy": direction[1],
        })
    # Worst first: paste-receiving overlaps are the ones that cost yield.
    rows.sort(key=lambda r: (not r["paste"], not r["overlaps"], -r["travel"]))
    return rows, target


# ---------------------------------------------------------------------------
# the guard: KiCad's own opinion, before and after every single move
# ---------------------------------------------------------------------------

def run_drc(board_path, workdir):
    out = os.path.join(workdir, "drc.json")
    cli = json.load(open(MANIFEST, encoding="utf-8"))["tools"]["kicad_cli"]
    proc = subprocess.run(
        [cli, "pcb", "drc", "-o", out, "--format", "json", "--severity-all",
         "--severity-exclusions", "--all-track-errors", board_path],
        capture_output=True, text=True)
    if not os.path.isfile(out):
        raise RuntimeError("DRC produced no report: "
                           + (proc.stderr or "")[:300])
    doc = json.load(open(out, encoding="utf-8"))
    counts = collections.Counter()
    for bucket in ("violations", "unconnected_items"):
        for item in doc.get(bucket, []):
            counts[item["type"]] += 1
    return counts


def move_via(board, index, new_x, new_y):
    """Move one via and drag every track endpoint that sat on it."""
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


def guarded_apply(board_path, rows, workdir):
    baseline = run_drc(board_path, workdir)
    print("baseline DRC: {} finding(s) {}".format(
        sum(baseline.values()), dict(baseline) or ""))
    kept, rejected = [], []
    backup = os.path.join(workdir, "revert.kicad_pcb")

    for row in rows:
        shutil.copy2(board_path, backup)
        placed = False
        for scale in STEP_SCALE:
            travel = row["travel"] * scale
            if travel > MAX_TRAVEL_MM:
                break
            shutil.copy2(backup, board_path)
            board = pcbnew.LoadBoard(board_path)
            dragged = move_via(board, row["index"],
                               row["x"] + row["dx"] * travel,
                               row["y"] + row["dy"] * travel)
            board.Save(board_path)
            after = run_drc(board_path, workdir)
            if after == baseline:
                kept.append((row, travel, dragged))
                print("  moved  {:.3f} mm  net {:<13} pad {:<9} paste={}"
                      .format(travel, row["net"][:13], str(row["pad"]),
                              row["paste"]))
                placed = True
                break
        if not placed:
            shutil.copy2(backup, board_path)
            worst = (after - baseline) if rows else {}
            rejected.append((row, dict(worst)))
            print("  KEPT AS-IS   net {:<13} pad {:<9}: every step introduced "
                  "{}".format(row["net"][:13], str(row["pad"]), dict(worst)))
    return kept, rejected, baseline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--all", action="store_true",
                        help="every via under target, not just the overlaps")
    parser.add_argument("--board", default=BOARD)
    args = parser.parse_args()

    manifest, _board, survey = load(args.board)
    rows, target = candidates(survey, manifest, everything=args.all)

    print("candidates: {}".format(len(rows)))
    print("  annulus overlapping an aperture : {}".format(
        len([r for r in rows if r["overlaps"]])))
    print("  pad receives solder paste       : {}".format(
        len([r for r in rows if r["paste"]])))
    print("  different net from the pad      : {}".format(
        len([r for r in rows if r["net"] != r["pad_net"]])))

    if not args.apply:
        for row in rows[:20]:
            print("  gap {:.3f}  need {:.3f}  net {:<13} pad {:<9} paste={}"
                  .format(row["gap"], row["travel"], row["net"][:13],
                          str(row["pad"]), row["paste"]))
        return 0

    workdir = tempfile.mkdtemp(prefix="relieve_")
    try:
        kept, rejected, baseline = guarded_apply(args.board, rows, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("\nmoved {} via(s); left {} alone".format(len(kept), len(rejected)))
    print("board DRC is unchanged from baseline: {} finding(s)".format(
        sum(baseline.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
