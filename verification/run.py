#!/usr/bin/env python
"""pcbqa - board-agnostic KiCad/JLCPCB verification.

    python run.py preflight [manifest]     diagnose the environment
    python run.py selftest [--jobs auto|N] run the validator's own test suite
    python run.py validate <manifest>      validate a board; nonzero if rejected
    python run.py release  <manifest>      clean-room release attempt
    python run.py gates                    list gate IDs

Run everything with KiCad's own Python. pcbnew, Shapely and kicad-cli are
externally supplied prerequisites; this tool reports what it finds and never
installs or pins them.

Fail-closed: a gate that cannot be evaluated reports ERROR and blocks, and the
release command never produces a sealed package.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Nothing that needs pcbnew or Shapely is imported at module scope: preflight
# has to be able to explain a broken environment, and it cannot do that if
# importing this file is what fails.


def _output_base():
    """Where run artifacts go. Workers override this so they never collide."""
    from pcbqa.parallel import ENV_OUTPUT_ROOT
    return os.environ.get(ENV_OUTPUT_ROOT, HERE)


def _load_gates():
    from pcbqa.gates import (g_provenance, g_checks, g_geometry,   # noqa: F401
                             g_contracts, g_assembly, g_export_parity)


def _load(manifest_path):
    from pcbqa.core import Context, Manifest
    _load_gates()
    manifest = Manifest(manifest_path)
    workdir = os.path.join(_output_base(), "out", manifest.get("board_id"))
    os.makedirs(workdir, exist_ok=True)
    ctx = Context(manifest, workdir)
    try:
        ctx.tool_versions["kicad"] = ctx.kicad_version()
    except Exception as exc:
        ctx.tool_versions["kicad"] = "UNAVAILABLE: {}".format(exc)
    return ctx


def _emit(ctx, results, tag):
    from pcbqa import core
    doc = core.to_json(results, ctx)
    jpath = os.path.join(ctx.workdir, tag + ".json")
    mpath = os.path.join(ctx.workdir, tag + ".md")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, default=str)
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write(core.to_markdown(doc))
    return doc, jpath, mpath


def cmd_validate(manifest_path, quiet=False):
    from pcbqa import core
    ctx = _load(manifest_path)
    results = core.run_all(ctx)
    doc, jpath, mpath = _emit(ctx, results, "validation")
    if not quiet:
        print(core.to_markdown(doc))
        print("\nJSON:     " + jpath + "\nMarkdown: " + mpath)
    return (1 if doc["summary"]["blocking"] else 0), doc, ctx


def cmd_release(manifest_path):
    """Clean-room release.

    Nothing that already exists in the tree can contribute to the verdict. The
    project is copied into an isolated run directory, every previously
    generated output is purged, and ERC, DRC, Gerbers, drills, BOM, CPL and the
    fabrication archive are regenerated there. Validation then runs against a
    derived manifest whose every authoritative path is proven to resolve inside
    that run, so the artifacts that are validated are the artifacts that were
    just generated. Success produces an UNSEALED candidate only.
    """
    from pcbqa import cleanroom, core
    from pcbqa.core import Context, Manifest, Status
    _load_gates()

    manifest = Manifest(manifest_path)
    base = os.path.join(_output_base(), "out", manifest.get("board_id"))
    os.makedirs(base, exist_ok=True)
    source_ctx = Context(manifest, os.path.join(base, "release_driver"))

    profile = manifest.get("release_profile", None)
    if not profile:
        print("RELEASE BLOCKED: manifest declares no release_profile")
        return 1
    mandatory = list(profile.get("mandatory_gates", []))
    if not mandatory:
        print("RELEASE BLOCKED: release profile names no mandatory gates")
        return 1
    if not manifest.has("release_generation"):
        print("RELEASE BLOCKED: manifest declares no release_generation block, "
              "so a clean-room run cannot be reproduced")
        return 1

    run = cleanroom.CleanRun(source_ctx, os.path.join(base, "clean_run"))
    derived = None
    try:
        derived = run.build()
    except cleanroom.CleanRoomError as exc:
        run.blockers.append(("release:cleanroom", "ERROR", str(exc)))
    except Exception as exc:                                   # fail closed
        run.blockers.append(("release:cleanroom", "ERROR",
                             f"{type(exc).__name__}: {exc}"))

    blockers = list(run.blockers)
    doc = jpath = mpath = None
    results = []
    if derived is not None:
        ctx = Context(derived, os.path.join(run.root, "validation"),
                      kicad_cli=source_ctx.kicad_cli)
        results = core.run_all(ctx)
        doc, jpath, mpath = _emit(ctx, results, "release_validation")
        doc["clean_room"] = run.summary()
        with open(jpath, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        print(core.to_markdown(doc))

        by_id = {r.gate_id: r for r in results}
        for gate_id in mandatory:
            result = by_id.get(gate_id)
            if result is None:
                blockers.append((gate_id, "MISSING", "mandatory gate did not run"))
            elif result.status != Status.PASS:
                blockers.append((gate_id, result.status, result.reason[:110]))
        for r in results:
            if r.status in Status.BLOCKING and r.gate_id not in mandatory:
                blockers.append((r.gate_id, r.status, "non-mandatory gate blocked"))

    sealed = os.path.join(base, "release_sealed")
    candidate = os.path.join(base, "release_candidate_UNSEALED")
    unsafe = os.path.join(base, "release_UNSAFE_diagnostic")
    for path in (sealed, candidate, unsafe):
        if os.path.isdir(path):
            shutil.rmtree(path)

    print(os.linesep + "Clean-room run: " + run.root)
    for entry in run.summary()["steps"]:
        if "exit" in entry:
            print("  {}: exit {}".format(entry["step"], entry["exit"]))
    print("  purged {} pre-existing output path(s)".format(
        len(run.summary()["purged"])))
    print("  {} authoritative path(s) proven inside the run".format(
        len(run.summary()["authoritative_paths"])))

    if blockers:
        os.makedirs(unsafe)
        lines = ["UNSAFE DIAGNOSTIC OUTPUT - NOT A RELEASE", "",
                 "board: " + str(manifest.get("board_id")),
                 "release profile: " + str(profile.get("id")),
                 "clean run: " + run.root, "", "blocking:"]
        for gate_id, status, why in blockers:
            lines.append("  {}: {} - {}".format(gate_id, status, why))
        lines += ["", "No sealed or orderable package was produced.", ""]
        with open(os.path.join(unsafe, "DO_NOT_ORDER.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(chr(10).join(lines))
        with open(os.path.join(unsafe, "clean_room.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(run.summary(), fh, indent=2)
        if jpath:
            shutil.copy2(jpath, os.path.join(unsafe, "validation.json"))
            shutil.copy2(mpath, os.path.join(unsafe, "validation.md"))
        print(chr(10) + "RELEASE BLOCKED by {} condition(s):".format(
            len(blockers)))
        for gate_id, status, why in blockers[:25]:
            print("  {}: {} - {}".format(gate_id, status, why))
        print("Unsafe diagnostic output only: " + unsafe)
        print("Sealed package created: NO")
        return 1

    os.makedirs(candidate)
    shutil.copytree(run.release, os.path.join(candidate, "fabrication"))
    shutil.copytree(run.reports, os.path.join(candidate, "reports"))
    shutil.copy2(jpath, os.path.join(candidate, "validation.json"))
    with open(os.path.join(candidate, "clean_room.json"), "w",
              encoding="utf-8") as fh:
        json.dump(run.summary(), fh, indent=2)
    with open(os.path.join(candidate, "UNSEALED.txt"), "w", encoding="utf-8") as fh:
        fh.write("Release CANDIDATE, not sealed.\n\n"
                 "Every artifact here was generated in this run from a clean "
                 "project copy with all prior output purged, and every "
                 "mandatory gate passed against those artifacts. Sealing "
                 "additionally requires recorded visual-review evidence "
                 "({}).\n"
                 .format(profile.get("visual_review_evidence")))
    print("\nUnsealed release candidate: " + candidate)
    print("Sealed package created: NO (sealing requires visual-review evidence)")
    return 0


def cmd_selftest(argv):
    from pcbqa import parallel
    parser = argparse.ArgumentParser(prog="run.py selftest")
    parser.add_argument("--jobs", default="auto",
                        help="worker processes: auto (default), 1, or a count")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="seconds before a stalled worker is killed")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args(argv[2:])
    code, _summary = parallel.run(os.path.join(HERE, "tests"), HERE,
                                  jobs=args.jobs, timeout_s=args.timeout,
                                  fail_fast=args.fail_fast,
                                  output_root=args.output_root)
    return code


def cmd_preflight(argv):
    from pcbqa import preflight
    kicad_cli = None
    if len(argv) > 2:
        manifest_path = argv[2]
    else:
        manifest_path = os.path.join(HERE, "boards", "reva.json")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            kicad_cli = json.load(fh).get("tools", {}).get("kicad_cli")
    except (OSError, ValueError) as exc:
        print(f"could not read {manifest_path}: {exc}")
    ok, rows = preflight.environment(kicad_cli)
    print("pcbqa preflight")
    print(preflight.report(rows))
    notes = preflight.advice(rows)
    if notes:
        print("")
        for line in notes:
            print(line)
    print("READY" if ok else "NOT READY")
    return 0 if ok else 1


def cmd_gates():
    from pcbqa import core
    _load_gates()
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
        return cmd_selftest(argv)
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
