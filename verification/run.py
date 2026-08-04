#!/usr/bin/env python
"""pcbqa - board-agnostic KiCad/JLCPCB verification.

    python run.py preflight [manifest]     report interpreter/KiCad/dependency versions
    python run.py selftest                 run the validator's own test suite
    python run.py validate <manifest>      validate a board; nonzero if rejected
    python run.py release  <manifest>      clean-room release attempt; blocked on failure
    python run.py gates                    list gate IDs

Fail-closed: a gate that cannot be evaluated reports ERROR and blocks, and the
release command never produces a sealed package.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pcbqa import core                                    # noqa: E402
from pcbqa.core import Context, Manifest, Status          # noqa: E402
from pcbqa.gates import (g_provenance, g_checks, g_geometry,   # noqa: E402,F401
                         g_contracts, g_assembly, g_export_parity)


def _load(manifest_path):
    manifest = Manifest(manifest_path)
    workdir = os.path.join(HERE, "out", manifest.get("board_id"))
    os.makedirs(workdir, exist_ok=True)
    ctx = Context(manifest, workdir)
    try:
        ctx.tool_versions["kicad"] = ctx.kicad_version()
    except Exception as exc:
        ctx.tool_versions["kicad"] = "UNAVAILABLE: {}".format(exc)
    return ctx


def _emit(ctx, results, tag):
    doc = core.to_json(results, ctx)
    jpath = os.path.join(ctx.workdir, tag + ".json")
    mpath = os.path.join(ctx.workdir, tag + ".md")
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
        print("\nJSON:     " + jpath + "\nMarkdown: " + mpath)
    return (1 if doc["summary"]["blocking"] else 0), doc, ctx


def cmd_release(manifest_path):
    """Clean-room release.

    Runs on a pristine copy of the project, regenerates every output the
    release would ship, then validates. A gate the release profile names
    mandatory must be PASS; NOT_APPLICABLE, ERROR, missing configuration or a
    gate that never ran all block, so a minimal manifest cannot buy a seal.
    Success produces an UNSEALED candidate only - sealing is a separate action
    that additionally requires recorded visual-review evidence.
    """
    ctx = _load(manifest_path)
    profile = ctx.manifest.get("release_profile", None)
    if not profile:
        print("RELEASE BLOCKED: manifest declares no release_profile")
        return 1
    mandatory = list(profile.get("mandatory_gates", []))
    if not mandatory:
        print("RELEASE BLOCKED: release profile names no mandatory gates")
        return 1

    clean = os.path.join(ctx.workdir, "clean_project")
    ctx.clean_copy(clean)
    regen = os.path.join(ctx.workdir, "regenerated")
    if os.path.isdir(regen):
        shutil.rmtree(regen)
    os.makedirs(regen)
    board = os.path.join(clean, ctx.manifest.get("sources.pcb"))
    steps = (
        ("gerbers", ["pcb", "export", "gerbers", "--output", regen, board]),
        ("drill", ["pcb", "export", "drill", "--output", regen,
                   "--format", "excellon", "--excellon-separate-th", board]),
        ("pos", ["pcb", "export", "pos", "--output", os.path.join(regen, "pos.csv"),
                 "--format", "csv", "--units", "mm", board]),
    )
    regen_log = []
    for name, args in steps:
        proc = ctx.run_tool([ctx.kicad_cli] + args)
        regen_log.append({"step": name, "exit": proc.returncode,
                          "stderr": proc.stderr.strip()[:200]})

    results = core.run_all(ctx)
    doc, jpath, mpath = _emit(ctx, results, "release_validation")
    print(core.to_markdown(doc))

    by_id = {r.gate_id: r for r in results}
    blockers = []
    for gate_id in mandatory:
        result = by_id.get(gate_id)
        if result is None:
            blockers.append((gate_id, "MISSING", "mandatory gate did not run"))
        elif result.status != Status.PASS:
            blockers.append((gate_id, result.status, result.reason[:110]))
    for r in results:
        if r.status in Status.BLOCKING and r.gate_id not in mandatory:
            blockers.append((r.gate_id, r.status, "non-mandatory gate blocked"))
    for entry in regen_log:
        if entry["exit"] != 0:
            blockers.append(("regenerate:" + entry["step"], "ERROR", entry["stderr"]))

    sealed = os.path.join(ctx.workdir, "release_sealed")
    candidate = os.path.join(ctx.workdir, "release_candidate_UNSEALED")
    unsafe = os.path.join(ctx.workdir, "release_UNSAFE_diagnostic")
    for path in (sealed, candidate, unsafe):
        if os.path.isdir(path):
            shutil.rmtree(path)

    if blockers:
        os.makedirs(unsafe)
        shutil.copy2(jpath, os.path.join(unsafe, "validation.json"))
        shutil.copy2(mpath, os.path.join(unsafe, "validation.md"))
        lines = ["UNSAFE DIAGNOSTIC OUTPUT - NOT A RELEASE", "",
                 "board: " + str(doc["manifest"]["board_id"]),
                 "release profile: " + str(profile.get("id")), "", "blocking:"]
        for gate_id, status, why in blockers:
            lines.append("  {}: {} - {}".format(gate_id, status, why))
        lines += ["", "No sealed or orderable package was produced.", ""]
        with open(os.path.join(unsafe, "DO_NOT_ORDER.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print("\nRELEASE BLOCKED by {} condition(s):".format(len(blockers)))
        for gate_id, status, why in blockers[:25]:
            print("  {}: {} - {}".format(gate_id, status, why))
        print("Unsafe diagnostic output only: " + unsafe)
        print("Sealed package created: NO")
        return 1

    os.makedirs(candidate)
    shutil.copytree(regen, os.path.join(candidate, "fabrication"))
    shutil.copy2(jpath, os.path.join(candidate, "validation.json"))
    with open(os.path.join(candidate, "UNSEALED.txt"), "w", encoding="utf-8") as fh:
        fh.write("Release CANDIDATE, not sealed.\n\n"
                 "Every mandatory gate passed and every artifact here was "
                 "generated in this run from a clean project copy. Sealing "
                 "additionally requires recorded visual-review evidence ({}).\n"
                 .format(profile.get("visual_review_evidence")))
    print("\nUnsealed release candidate: " + candidate)
    print("Sealed package created: NO (sealing requires visual-review evidence)")
    return 0


def cmd_selftest():
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(HERE, "tests"), top_level_dir=HERE)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def cmd_preflight(argv):
    from pcbqa import preflight
    manifest_path = argv[2] if len(argv) > 2 else os.path.join(
        HERE, "boards", "reva.json")
    cli = Manifest(manifest_path).get("tools.kicad_cli")
    ok, rows = preflight.check(cli, os.path.join(HERE, "requirements.txt"))
    print("pcbqa preflight")
    print(preflight.report(rows))
    print("READY" if ok else "NOT READY")
    return 0 if ok else 1


def cmd_gates():
    for entry in core.registered():
        req = ", ".join(entry["requires"]) or "-"
        print("{:32s} {}".format(entry["id"], entry["title"]))
        print("{:32s} requires: {}".format("", req))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "preflight":
        return cmd_preflight(argv)
    if cmd == "selftest":
        return cmd_selftest()
    if cmd == "gates":
        return cmd_gates()
    if cmd in ("validate", "release"):
        if len(argv) < 3:
            print("usage: run.py {} <manifest.json>".format(cmd))
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
