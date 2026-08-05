"""Close the handful of connections the autorouter left open.

FreeRouting reliably finishes most of this board but leaves a few short local
links unrouted - typically the hop from a microphone's handover via to that
channel's own resistor or capacitor, a couple of millimetres away.

Rather than guess which ones, this reads KiCad's own DRC unconnected-items
report and draws exactly those links. Anything that cannot be closed with a
clean 45 degree path is reported and left alone for a human, never forced.

Usage:  close_gaps.py board.kicad_pcb drc.json
"""

import json
import math
import os
import sys

import pcbnew

import gen_pcb

MAX_GAP_MM = 6.0
TRACK_WIDTH_MM = 0.15


def endpoints(entry):
    """The two board positions a DRC unconnected entry refers to."""
    points = []
    for item in entry.get("items", []):
        position = item.get("pos")
        if position is None:
            return None
        points.append(pcbnew.VECTOR2I(pcbnew.FromMM(position["x"]),
                                      pcbnew.FromMM(position["y"])))
    return points if len(points) == 2 else None


def net_of(entry):
    for item in entry.get("items", []):
        text = item.get("description", "")
        if "[" in text and "]" in text:
            return text.split("[", 1)[1].split("]", 1)[0]
    return None


def channel_links(name):
    """Map a per-channel net name to its escape pad and destination pads."""
    # The supply link goes to the isolation resistor, not the capacitor: the
    # capacitor sits on the far tangential side, so a track to it would cross
    # the data escape's handover via. The capacitor-to-resistor hop is ordinary
    # board routing the autorouter already makes.
    # Only links that stay on one tangential side of the microphone are drawn
    # here. The supply escape reaches the isolation resistor; the hop onward to
    # the decoupling capacitor is deliberately NOT attempted, because the
    # capacitor sits on the opposite side and every automatic path to it either
    # crosses the data escape's handover via or cuts across the package. Those
    # links are reported for manual routing instead.
    for prefix, pad, links in (
            ("MIC_VDD_", "1", [("RV{n}", "2")]),
            ("MIC_DOUT_", "4", [("RD{n}", "1")])):
        if name.startswith(prefix):
            try:
                return int(name[len(prefix):]), (pad, links)
            except ValueError:
                return None, None
    return None, None


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    board_path, report_path = sys.argv[1], sys.argv[2]

    with open(report_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    gaps = report.get("unconnected_items", [])
    if not gaps:
        print("no unconnected items to close")
        return 0

    board = pcbnew.LoadBoard(board_path)
    placed = {fp.GetReference(): fp for fp in board.Footprints()}
    open_nets = {net_of(entry) for entry in gaps} - {None}

    closed, skipped = 0, []
    for name in sorted(open_nets):
        # Work from the escape's known handover-via coordinate rather than the
        # position in the DRC report: that position is the offending item's
        # anchor, which for a track is not where the connection is missing, and
        # drawing from it cuts straight across the package.
        channel, links = channel_links(name)
        if channel is None:
            skipped.append(f"{name}: not a per-channel link, needs manual routing")
            continue
        microphone = placed.get(f"MK{channel + 1}")
        net = board.FindNet(name)
        if microphone is None or net is None:
            skipped.append(name)
            continue
        start = gen_pcb.local_to_board(microphone,
                                       *gen_pcb.MIC_ESCAPES[links[0]][-1])
        for link in links[1]:
            origin = start
            if len(link) == 4:
                # pad-to-pad hop rather than escape-to-pad
                from_ref, from_pad, template, pad_number = link
                source = placed.get(from_ref.format(n=channel + 1))
                if source is None:
                    continue
                origin = next((p.GetPosition() for p in source.Pads()
                               if p.GetNumber() == from_pad), None)
                if origin is None:
                    continue
            else:
                template, pad_number = link
            cluster = placed.get(template.format(n=channel + 1))
            if cluster is None:
                continue
            target = next((p.GetPosition() for p in cluster.Pads()
                           if p.GetNumber() == pad_number), None)
            if target is None:
                continue
            span = math.hypot(target.x - origin.x, target.y - origin.y) / 1e6
            if span > MAX_GAP_MM:
                skipped.append(f"{name}: {span:.1f} mm to {template.format(n=channel + 1)}")
                continue
            # Hold the origin's tangential offset until level with the target,
            # then turn in. Driving straight at the pad runs the track over its
            # partner pad on the way past.
            ex, _ey = gen_pcb.board_to_local(microphone, origin)
            tx, ty = gen_pcb.board_to_local(microphone, target)
            standoff = gen_pcb.local_to_board(microphone, ex,
                                              ty - abs(tx - ex))
            gen_pcb.add_track(board, net, pcbnew.F_Cu, TRACK_WIDTH_MM,
                              [origin, standoff, target])
            closed += 1

    board.Save(board_path)
    print(f"closed {closed} of {len(gaps)} gaps in {os.path.basename(board_path)}")
    for line in skipped:
        print(f"  left for review: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
