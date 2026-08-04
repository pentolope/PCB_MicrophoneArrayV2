"""Transplant a FreeRouting candidate's copper onto the authoritative board.

KiCad's Specctra SES import re-applies component placement from the session
file, and Specctra stores component rotation in whole degrees. Importing a
candidate therefore rounds every non-integer footprint angle - 33.75 becomes
34.0 - and quietly moves 88 of this board's 134 footprints. The array geometry
is built on 22.5 degree steps, so that is not acceptable.

FreeRouting's remit is tracks and vias only, so this script keeps the
pre-route board as the authority for everything else and copies just the copper
across.

Usage:  merge_routing.py authority.kicad_pcb routed.kicad_pcb output.kicad_pcb
"""

import os
import sys

import pcbnew


# The only via geometries this project allows, as (pad, finished hole) in mm.
ALLOWED_VIAS = ((0.45, 0.30), (0.60, 0.35))


def snap_via(width_nm, drill_nm):
    """Return the declared via geometry closest to what the router produced."""
    width_mm = width_nm / 1e6
    diameter, drill = min(ALLOWED_VIAS, key=lambda v: abs(v[0] - width_mm))
    return pcbnew.FromMM(diameter), pcbnew.FromMM(drill)


def copy_copper(source, target):
    """Replace target's tracks and vias with source's."""
    # Materialise both collections before mutating either board; the SWIG
    # wrappers do not survive being re-fetched after a Remove().
    incoming = list(source.Tracks())
    for item in list(target.Tracks()):
        target.Remove(item)

    nets = {}
    for item in incoming:
        name = item.GetNetname()
        if name and name not in nets:
            found = target.FindNet(name)
            if found is not None:
                nets[name] = found

    copied, vias = 0, 0
    for item in incoming:
        name = item.GetNetname()
        net = nets.get(name)
        if net is None and name:
            continue
        if isinstance(item, pcbnew.PCB_VIA):
            via = pcbnew.PCB_VIA(target)
            via.SetPosition(item.GetPosition())
            via.SetViaType(item.GetViaType())
            top, bottom = item.TopLayer(), item.BottomLayer()
            via.SetLayerPair(top, bottom)
            # FreeRouting emits vias that mix one class's pad diameter with
            # another's drill - 0.45 mm pad on a 0.35 mm drill, a 0.05 mm
            # annular ring. Snap every via back onto the project's declared
            # via inventory.
            diameter, drill = snap_via(item.GetWidth(top), item.GetDrillValue())
            via.SetWidth(diameter)
            via.SetDrill(drill)
            if net is not None:
                via.SetNet(net)
            via.SetFrontTentingMode(pcbnew.TENTING_MODE_TENTED)
            via.SetBackTentingMode(pcbnew.TENTING_MODE_TENTED)
            target.Add(via)
            vias += 1
        else:
            track = pcbnew.PCB_TRACK(target)
            track.SetStart(item.GetStart())
            track.SetEnd(item.GetEnd())
            track.SetWidth(item.GetWidth())
            track.SetLayer(item.GetLayer())
            if net is not None:
                track.SetNet(net)
            target.Add(track)
            copied += 1
    return copied, vias


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    authority_path, routed_path, output_path = sys.argv[1:4]

    authority = pcbnew.LoadBoard(authority_path)
    routed = pcbnew.LoadBoard(routed_path)
    tracks, vias = copy_copper(routed, authority)

    # Zones are deliberately not refilled here. The board still carries the
    # microphone corridor keepouts at this point, and running ZONE_FILLER over
    # a board containing rule areas kills the interpreter outright. The fill
    # happens in tools/apply_escapes.py, once the keepouts have been removed.
    authority.Save(output_path)
    print(f"merged {tracks} tracks and {vias} vias into "
          f"{os.path.basename(output_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
