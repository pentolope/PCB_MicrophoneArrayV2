"""Mark the inner copper layers as plane layers in an exported Specctra DSN.

KiCad exports every copper layer as `(type signal)`, which leaves FreeRouting
free to lay signal traces across both ground planes. FreeRouting 2.2.4 does not
accept the `--router.layers.routable` command-line option that would otherwise
restrict this - it reports "Unknown settings property" and carries on routing
all four layers - so the restriction is applied to the DSN itself, which is the
part of the exchange FreeRouting definitely honours.

Usage:  patch_dsn.py board.dsn GND1 GND2
"""

import re
import sys


def protect_wiring(text):
    """Promote every exported wire from `route` to `protect`.

    Off by default: FreeRouting 2.2.4 dies with a StackOverflowError inside
    PolylineTrace.combine about two seconds after loading a DSN whose wiring is
    marked `protect`, so the pre-routed copper is instead handed over as
    ordinary wiring. That is safe in practice - the microphone escapes are the
    only way out of the ground ring, so no cheaper alternative exists for the
    router to prefer - and `tools/check_routes.py` re-checks the geometry after
    import either way.
    """
    return re.subn(r"\(type route\)", "(type protect)", text)


def patch(path, plane_layers, protect=False):
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()

    protected = 0
    if protect:
        text, protected = protect_wiring(text)
    changed = []
    for layer in plane_layers:
        pattern = re.compile(
            r"(\(layer\s+" + re.escape(layer) + r"\s*\r?\n\s*\(type\s+)signal(\))")
        text, count = pattern.subn(r"\1power\2", text)
        if count:
            changed.append(layer)

    missing = sorted(set(plane_layers) - set(changed))
    if missing:
        raise SystemExit(f"layers not found or already patched: {missing}")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return changed, protected


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    args = [a for a in sys.argv[1:] if a != "--protect"]
    patched, protected = patch(args[0], args[1:],
                               protect="--protect" in sys.argv)
    print(f"marked as plane layers: {', '.join(patched)}; "
          f"protected {protected} existing wires")
