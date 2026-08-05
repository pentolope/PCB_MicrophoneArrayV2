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
import re
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


# A board id names one directory under `out/`. It arrives from a manifest that
# nobody has validated yet - the whole point of reading it early is that it is
# read *before* the manifest is trusted - and it is then used to choose a
# directory that gets deleted. So it is a single conservative slug or it is
# nothing: must start alphanumeric, may then contain alphanumerics, dot,
# underscore and hyphen, and nothing else. That admits every board id in this
# repository and admits no path syntax at all - no separator, no drive letter,
# no `..`, no leading dot, no whitespace, no NUL.
BOARD_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
BOARD_ID_MAX = 100


def valid_board_id(value):
    """True only for a name safe to use as a single path component."""
    if not isinstance(value, str):
        return False
    if not value or len(value) > BOARD_ID_MAX:
        return False
    if not BOARD_ID_RE.match(value):
        return False
    # Belt and braces: the regex already excludes these, but the cost of
    # asserting it directly is nothing next to the cost of being wrong.
    if value in (os.curdir, os.pardir):
        return False
    if os.path.basename(value) != value:
        return False
    drive, _tail = os.path.splitdrive(value)
    return not drive


def managed_output_dir(manifest_path):
    """Where this board's release output lives. Returns None if unidentifiable.

    Called before the gates are imported and before the manifest is
    constructed, because both of those can fail and a release that fails is
    still a release that must not leave an old candidate behind.

    The manifest must be a JSON *object* and its `board_id` must be a safe
    single path component. There is deliberately no salvage path for malformed
    JSON: the value chosen here selects a directory that this command will
    delete from, and guessing it out of a file that does not parse is how a
    cleanup routine ends up removing somebody else's work. A manifest we cannot
    read is a manifest whose board we do not know, and not knowing is a reason
    to stop rather than to guess.
    """
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            document = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    if not valid_board_id(document.get("board_id")):
        return None

    root = os.path.realpath(os.path.join(_output_base(), "out"))
    candidate = os.path.realpath(os.path.join(root, document["board_id"]))
    # Strictly beneath, and exactly one level down. This also catches the case
    # where `out/<id>` is a symlink pointing somewhere else entirely, because
    # realpath has already followed it by the time we look.
    if candidate == root or os.path.dirname(candidate) != root:
        return None
    return candidate


def cmd_release(manifest_path):
    """Clean-room release.

    Nothing that already exists in the tree can contribute to the verdict, and
    nothing orderable exists in the managed output until the verdict is in. The
    project is copied into an isolated run directory, every previously
    generated output is purged, and ERC, DRC, Gerbers, drills, BOM, CPL and the
    fabrication archive are regenerated. The package is assembled in staging
    *outside* the output tree and moved in by a single rename, which is the
    last operation of a successful run.

    The cleanup contract is established first - before the optional gate
    modules are imported, before the manifest is constructed, and before it is
    validated. Every one of those can fail, and each failure is still a failed
    release: it must not leave yesterday's candidate sitting in the output
    directory looking current.
    """
    from pcbqa import cleanroom

    base = managed_output_dir(manifest_path)
    state = {"succeeded": False, "run": None}
    try:
        if base is None:
            print("RELEASE BLOCKED: cannot identify the board this manifest "
                  "describes, so nothing can be released from it")
            return 1
        os.makedirs(base, exist_ok=True)
        _load_gates()                       # optional, and able to fail
        from pcbqa.core import Manifest
        manifest = Manifest(manifest_path)  # validates schema_version, JSON
        return _release_preconditions_and_attempt(manifest, base, state)
    except KeyboardInterrupt:
        print(chr(10) + "RELEASE ABANDONED: interrupted before it could "
                        "complete")
        return 130
    except BaseException as exc:                              # fail closed
        print(chr(10) + "RELEASE BLOCKED by an unhandled {}: {}".format(
            type(exc).__name__, exc))
        return 1
    finally:
        run = state["run"]
        if run is not None:
            run.discard_staging()
            run.discard_pending()
        if not state["succeeded"] and base is not None:
            swept = cleanroom.purge_managed_output(
                base, os.path.dirname(base))
            if swept:
                print("Removed {} orderable artifact(s) from a release that "
                      "did not succeed".format(len(swept)))
            left = cleanroom.orderable_archives(base)
            if left:
                print("WARNING: orderable archive(s) remain: {}".format(left))


def _release_preconditions_and_attempt(manifest, base, state):
    from pcbqa import cleanroom
    from pcbqa.core import Context

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

    sealed = os.path.join(base, "release_sealed")
    candidate = os.path.join(base, "release_candidate_UNSEALED")
    unsafe = os.path.join(base, "release_UNSAFE_diagnostic")

    source_ctx = Context(manifest, os.path.join(base, "release_driver"))
    run = cleanroom.CleanRun(source_ctx, os.path.join(base, "clean_run"))
    state["run"] = run
    code = _release_attempt(run, manifest, profile, mandatory, base,
                            sealed, candidate, unsafe)
    state["succeeded"] = (code == 0) and run.succeeded
    return code


def _release_attempt(run, manifest, profile, mandatory, base,
                     sealed, candidate, unsafe):
    from pcbqa import cleanroom, core
    from pcbqa.core import Context, Status

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
                      kicad_cli=run.source_ctx.kicad_cli)
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
    print("  package staged outside the output tree: " + run.staging)

    if blockers:
        _write_unsafe(unsafe, run, manifest, profile, blockers, jpath, mpath)
        print(chr(10) + "RELEASE BLOCKED by {} condition(s):".format(
            len(blockers)))
        for gate_id, status, why in blockers[:25]:
            print("  {}: {} - {}".format(gate_id, status, why))
        print("Unsafe diagnostic output only: " + unsafe)
        print("Sealed package created: NO")
        print("Fabrication archive created: NO")
        return 1

    # Every mandatory gate passed. Assemble the candidate in full outside the
    # output tree; a failure anywhere below leaves the output tree untouched.
    try:
        pending = run.stage_candidate()
        shutil.copytree(run.reports, os.path.join(pending, "reports"))
        shutil.copy2(jpath, os.path.join(pending, "validation.json"))
        with open(os.path.join(pending, "clean_room.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(run.summary(), fh, indent=2)
        with open(os.path.join(pending, "UNSEALED.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(_unsealed_text(profile))
        promoted = run.commit_candidate(candidate)   # last operation, atomic
    except BaseException as exc:
        # Includes KeyboardInterrupt. Whatever went wrong, this attempt did
        # not produce a release, and the only thing it may leave behind is a
        # diagnostic saying so.
        run.discard_pending()
        run.sweep_output_tree(base)
        _write_unsafe(unsafe, run, manifest, profile,
                      [("release:promotion", "ERROR",
                        "{}: {}".format(type(exc).__name__, exc))],
                      jpath, mpath)
        print(chr(10) + "RELEASE BLOCKED: promotion failed after every gate "
                        "passed ({}: {})".format(type(exc).__name__, exc))
        print("Unsafe diagnostic output only: " + unsafe)
        print("Sealed package created: NO")
        print("Fabrication archive created: NO")
        if isinstance(exc, KeyboardInterrupt):
            raise
        return 1

    print(chr(10) + "Unsealed release candidate: " + candidate)
    print("Promoted from staging: " + ", ".join(promoted))
    print("Sealed package created: NO (sealing requires visual-review evidence)")
    return 0


def _unsealed_text(profile):
    return ("Release CANDIDATE, not sealed." + chr(10) + chr(10)
            + "Every artifact here was generated in this run from a clean "
              "project copy with all prior output purged, and every mandatory "
              "gate passed against those artifacts before the candidate was "
              "assembled. The whole candidate was built in temporary storage "
              "and moved here in one operation, so this directory is never "
              "partially written. Sealing additionally requires recorded "
              "visual-review evidence ({}).".format(
                  profile.get("visual_review_evidence")) + chr(10))


def _write_unsafe(unsafe, run, manifest, profile, blockers, jpath, mpath):
    """The only thing an unsuccessful attempt may leave behind."""
    if os.path.isdir(unsafe):
        shutil.rmtree(unsafe)
    os.makedirs(unsafe)
    lines = ["UNSAFE DIAGNOSTIC OUTPUT - NOT A RELEASE", "",
             "board: " + str(manifest.get("board_id")),
             "release profile: " + str(profile.get("id")),
             "clean run: " + run.root, "",
             "No fabrication archive was promoted; the staged package has "
             "been destroyed.", "", "blocking:"]
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
