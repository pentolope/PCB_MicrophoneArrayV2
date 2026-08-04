#!/usr/bin/env python
"""pcbqa - board-agnostic KiCad/JLCPCB verification.

    python run.py selftest                 run the validator's own test suite
    python run.py validate <manifest>      validate a board; nonzero if rejected
    python run.py release  <manifest>      attempt a release; blocked on any failure
    python run.py gates                    list gate IDs

The validator is fail-closed: a gate that cannot be evaluated reports ERROR and
blocks, and the release command never produces a sealed package when any gate
is not PASS or NOT_APPLICABLE.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pcbqa import core                                   # noqa: E402
from pcbqa.core import Context, Manifest, Status         # noqa: E402
from pcbqa.gates import g_provenance, g_geometry, g_contracts   # noqa: E402,F401


SEALED_MARKER = "SEALED_RELEASE.json"


def _load(manifest_path):
    manifest = Manifest(manifest_path)
    workdir = os.path.join(HERE, "out", manifest.get("board_id"))
    os.makedirs(workdir, exist_ok=True)
    ctx = Context(manifest, workdir)
    try:
        ctx.tool_versions["kicad"] = ctx.kicad_version()
    except Exception as exc:                              # fail closed
        ctx.tool_versions["kicad"] = f"UNAVAILABLE: {exc}"
    return ctx


def _emit(ctx, results, tag):
    doc = core.to_json(results, ctx)
    jpath = os.path.join(ctx.workdir, f"{tag}.json")
    mpath = os.path.join(ctx.workdir, f"{tag}.md")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, default=str)
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write(core.to_markdown(doc))
    return doc, jpath, mpath


def cmd_validate(manifest_path, quiet=False):
    ctx = _load(manifest_path)
    results = core.run_all(ctx)
    doc, jpath, mpath = _emit(ctx, results, "validation")
    if not quiet:
        print(core.to_markdown(doc))
        print(f"\nJSON:     {jpath}\nMarkdown: {mpath}")
    blocking = doc["summary"]["blocking"]
    return (1 if blocking else 0), doc, ctx


def cmd_release(manifest_path):
    """Clean-room release: validate first, package only if nothing blocks."""
    ctx = _load(manifest_path)
    stage = os.path.join(ctx.workdir, "release_stage")
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)

    results = core.run_all(ctx)
    doc, jpath, mpath = _emit(ctx, results, "release_validation")
    blocking = doc["summary"]["blocking"]
    print(core.to_markdown(doc))

    sealed_dir = os.path.join(ctx.workdir, "release_sealed")
    unsafe_dir = os.path.join(ctx.workdir, "release_UNSAFE_diagnostic")
    for d in (sealed_dir, unsafe_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)

    if blocking:
        os.makedirs(unsafe_dir)
        shutil.copy2(jpath, os.path.join(unsafe_dir, "validation.json"))
        shutil.copy2(mpath, os.path.join(unsafe_dir, "validation.md"))
        with open(os.path.join(unsafe_dir, "DO_NOT_ORDER.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(
                "UNSAFE DIAGNOSTIC OUTPUT - NOT A RELEASE\n\n"
                f"board: {doc['manifest']['board_id']}\n"
                f"blocking gates ({len(blocking)}): {', '.join(blocking)}\n\n"
                "No sealed production package was produced. Do not send anything "
                "in this directory to a fabricator.\n")
        print(f"\nRELEASE BLOCKED by {len(blocking)} gate(s): {', '.join(blocking)}")
        print(f"Unsafe diagnostic output only: {unsafe_dir}")
        print(f"Sealed package created: NO")
        return 1

    os.makedirs(sealed_dir)
    with open(os.path.join(sealed_dir, SEALED_MARKER), "w", encoding="utf-8") as fh:
        json.dump({"sealed": True, "validation": doc["summary"]}, fh, indent=2)
    print(f"\nRelease sealed: {sealed_dir}")
    return 0


def cmd_selftest():
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(HERE, "tests"), top_level_dir=HERE)
    runner = unittest.TextTestRunner(verbosity=2)
    return 0 if runner.run(suite).wasSuccessful() else 1


def cmd_gates():
    for entry in core.registered():
        req = ", ".join(entry["requires"]) or "-"
        print(f"{entry['id']:32s} {entry['title']}\n{'':32s} requires: {req}")
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "selftest":
        return cmd_selftest()
    if cmd == "gates":
        return cmd_gates()
    if cmd in ("validate", "release"):
        if len(argv) < 3:
            print(f"usage: run.py {cmd} <manifest.json>")
            return 2
        path = argv[2]
        if not os.path.isfile(path):
            path = os.path.join(HERE, "boards", argv[2])
        if cmd == "validate":
            return cmd_validate(path)[0]
        return cmd_release(path)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
