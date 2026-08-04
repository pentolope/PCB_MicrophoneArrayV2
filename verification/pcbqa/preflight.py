"""Environment preflight: report interpreter, KiCad and dependency versions."""

from __future__ import annotations

import os
import re
import subprocess
import sys

MIN_PYTHON = (3, 11)
SUPPORTED_KICAD = ("10.0",)
REQUIRED = {"shapely": "2.1", "pcbnew": None}


def _requirements(path):
    pins = {}
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if "==" in line:
                name, ver = line.split("==", 1)
                pins[name.strip()] = ver.strip()
    return pins


def check(kicad_cli, requirements_path):
    rows, ok = [], True

    version = tuple(sys.version_info[:2])
    good = version >= MIN_PYTHON
    ok &= good
    rows.append(("python", ".".join(map(str, sys.version_info[:3])),
                 f">= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}", good))

    try:
        import pcbnew
        build = pcbnew.GetBuildVersion()
        good = any(build.startswith(v) for v in SUPPORTED_KICAD)
        rows.append(("pcbnew", build, " or ".join(SUPPORTED_KICAD), good))
    except Exception as exc:
        good = False
        rows.append(("pcbnew", f"unavailable: {exc}", " or ".join(SUPPORTED_KICAD), False))
    ok &= good

    pins = _requirements(requirements_path)
    for name, want in pins.items():
        try:
            mod = __import__(name)
            have = getattr(mod, "__version__", "?")
            good = have == want
            rows.append((name, have, f"== {want}", good))
        except Exception as exc:
            good = False
            rows.append((name, f"missing: {exc}", f"== {want}", False))
        ok &= good

    if kicad_cli and os.path.isfile(kicad_cli):
        try:
            out = subprocess.run([kicad_cli, "--version"], capture_output=True,
                                 text=True, timeout=120)
            build = (out.stdout or out.stderr).strip().splitlines()[0]
            good = any(build.startswith(v) for v in SUPPORTED_KICAD)
        except Exception as exc:
            build, good = f"unavailable: {exc}", False
        rows.append(("kicad-cli", build, " or ".join(SUPPORTED_KICAD), good))
        ok &= good
    else:
        rows.append(("kicad-cli", f"not found at {kicad_cli}", "path must exist", False))
        ok = False

    return ok, rows


def report(rows):
    width = max(len(r[0]) for r in rows)
    lines = []
    for name, have, want, good in rows:
        mark = "ok  " if good else "FAIL"
        lines.append(f"  [{mark}] {name.ljust(width)}  {have}   (requires {want})")
    return chr(10).join(lines)
