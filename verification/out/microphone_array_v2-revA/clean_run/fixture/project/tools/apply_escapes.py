"""Add the microphone escape routing to a board that FreeRouting has returned.

FreeRouting 2.2.4 cannot handle these paths in either direction: it will not
create them itself, because its bounding-octagon pad approximation closes the
0.566 mm diagonal corners, and it hangs in "Wiring: normalization of net ..."
when they are supplied to it as existing wiring. So the board handed to the
autorouter is generated with `--no-escapes`, and this script lays the escapes
down afterwards, on the routed result.

Usage:  apply_escapes.py routed.kicad_pcb
"""

import os
import sys

import pcbnew

import gen_pcb
import netlist as nl


# Handover via -> the channel's own component. The autorouter usually makes
# these itself, but leaves a handful unrouted; drawing them for every channel
# is harmless where one already exists, because the duplicate is on the same
# net.
CLUSTER_LINKS = {
    "1": [("CM{n}", "1"), ("RV{n}", "2")],
    "4": [("RD{n}", "1")],
}


def already_joined(connectivity, pad_a, pad_b):
    """True when two pads are already electrically connected on the board."""
    try:
        connected = connectivity.GetConnectedPads(pad_a)
    except Exception:
        return False
    position = pad_b.GetPosition()
    for other in connected:
        if (other.GetPosition() == position
                and other.GetNumber() == pad_b.GetNumber()):
            return True
    return False


def connect_cluster_stubs(board, placed, pin_net, net_items):
    """Join each escape's handover via to the channel's own passives.

    Only where the autorouter did not already make the connection. Drawing
    these unconditionally produced 69 shorting-item violations, because the
    stub is laid straight through whatever the router had already put in that
    space.
    """
    connectivity = board.GetConnectivity()
    connectivity.RecalculateRatsnest()
    added = 0
    for k in range(gen_pcb.d.MIC_COUNT):
        ref = f"MK{k + 1}"
        footprint = placed[ref]
        for number, links in CLUSTER_LINKS.items():
            net = net_items[pin_net[(ref, number)]]
            start = gen_pcb.local_to_board(footprint,
                                           *gen_pcb.MIC_ESCAPES[number][-1])
            for template, pad_number in links:
                cluster = placed.get(template.format(n=k + 1))
                if cluster is None:
                    continue
                pad = next((p for p in cluster.Pads()
                            if p.GetNumber() == pad_number), None)
                if pad is None:
                    continue
                source = next((p for p in footprint.Pads()
                               if p.GetNumber() == number), None)
                if source is not None and already_joined(connectivity, source,
                                                         pad):
                    continue
                target = pad.GetPosition()
                # Approach along the escape's own tangential offset, turning in
                # only at the end, so the track never runs over the component's
                # other pad on the way past.
                ex, _ey = gen_pcb.board_to_local(footprint, start)
                tx, ty = gen_pcb.board_to_local(footprint, target)
                standoff = gen_pcb.local_to_board(footprint, ex,
                                                  ty - abs(tx - ex))
                added += gen_pcb.add_track(board, net, pcbnew.F_Cu, 0.15,
                                           [start, standoff, target])
    return added


def clock_escape_end(footprint):
    """Board position where a microphone's clock escape stops."""
    return gen_pcb.local_to_board(footprint, *gen_pcb.MIC_ESCAPES["3"][-1])


def complete_clock_branches(board, placed, net_items):
    """Join each microphone's clock escape to its branch resistor.

    The autorouter never reaches a microphone clock pad, so it leaves the
    branch trunk stranded. Each escape end is dropped to B.Cu - much emptier
    than the top - carried radially inward, and brought back up at the branch
    resistor.
    """
    added = 0
    for branch in range(8):
        net = net_items[f"PDM_CLK_B{branch}"]
        resistor = placed[f"RC{branch + 1}"]
        target = next(p.GetPosition() for p in resistor.Pads()
                      if p.GetNumber() == "2")
        hub = gen_pcb.add_via(board, net, target, offset_mm=1.4)
        added += gen_pcb.add_track(board, net, pcbnew.F_Cu, 0.25,
                                   gen_pcb.path_45(target, hub))

        for index in (2 * branch, 2 * branch + 1):
            microphone = placed[f"MK{index + 1}"]
            end = clock_escape_end(microphone)
            drop = gen_pcb.add_via(board, net, end, offset_mm=0.0)
            added += gen_pcb.add_track(board, net, pcbnew.B_Cu, 0.25,
                                       gen_pcb.path_45(drop, hub))
    return added


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]

    # Two passes, and they must be separate processes. Continuing to use a
    # board after removing items from it segfaults pcbnew, and calling
    # LoadBoard a second time in one process returns a wrapper that has lost
    # its methods. So `--strip-keepouts` does the removal and exits.
    if "--strip-keepouts" in sys.argv:
        board = pcbnew.LoadBoard(path)
        removed = 0
        for zone in list(board.Zones()):
            if zone.GetZoneName().startswith("MIC_ESCAPE_"):
                board.Remove(zone)
                removed += 1
        board.Save(path)
        print(f"removed {removed} corridor keepouts")
        return 0

    board = pcbnew.LoadBoard(path)
    for zone in board.Zones():
        if zone.GetZoneName().startswith("MIC_ESCAPE_"):
            raise SystemExit(
                "corridor keepouts are still present; run with "
                "--strip-keepouts first")

    _components, nets = nl.build()
    pin_net = {}
    for name, pins in nets.items():
        for ref, pad in pins:
            pin_net[(ref, pad)] = name

    placed = {fp.GetReference(): fp for fp in board.Footprints()}
    net_items = {}
    for name in nets:
        item = board.FindNet(name)
        if item is None:
            raise SystemExit(f"net missing from routed board: {name}")
        net_items[name] = item

    added = gen_pcb.route_microphone_escapes(board, placed, pin_net, net_items)

    # Zones are refilled by `kicad-cli pcb drc --refill-zones --save-board`
    # rather than here: pcbnew's ZONE_FILLER segfaults on this board once the
    # full routing is present.
    board.Save(path)
    print(f"added {added} escape segments to {os.path.basename(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
