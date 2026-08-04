"""Contract, BOM/CPL parity, archive and constraint-parity gates."""

from __future__ import annotations

import ast
import csv
import glob
import io
import json
import os
import re
import zipfile
from collections import Counter

from ..core import Status, gate, sha256_file, sha256_bytes
from .. import gerber
from ..rules import NetTopologyRule, ConnectorContractRule, PlacementRule


def _docs(ctx, patterns):
    root = ctx.manifest.resolve(".")
    out = {}
    for pat in patterns:
        for path in glob.glob(os.path.join(root, pat), recursive=True):
            if os.path.isfile(path):
                rel = os.path.relpath(path, root).replace("\\", "/")
                try:
                    out[rel] = open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    pass
    return out


# ---------------------------------------------------------------------------
# net topology
# ---------------------------------------------------------------------------

@gate("NET.TOPOLOGY", "Critical-net topology and length matching",
      requires=("net_topology.rules",))
def net_topology(ctx, res):
    board = ctx.board()
    problems = []
    for index, spec in enumerate(ctx.manifest.get("net_topology.rules")):
        rule = NetTopologyRule(spec)
        measured, issues = rule.evaluate(board)
        issues += rule.check_limits(measured)
        res.measurements[spec["id"]] = {
            "nets": len(measured),
            "per_net": [{"net": m["net"], "max_path_mm": m["max_path_mm"],
                         "min_path_mm": m["min_path_mm"], "vias": m["vias"],
                         "layers": m["layers"], "branch_points": m["branch_points"],
                         "total_copper_mm": m["total_copper_mm"]} for m in measured],
        }
        maxima = [m["max_path_mm"] for m in measured if m["max_path_mm"] is not None]
        if maxima:
            res.measurements[spec["id"]]["spread_mm"] = round(max(maxima) - min(maxima), 3)
        for key in ("max_spread_mm", "max_vias_per_net"):
            if key in spec:
                res.limit(f"{spec['id']}.{key}", spec[key],
                          ctx.manifest.source_of(
                              f"net_topology.rules.{index}.{key}"))
        for issue in issues:
            problems.append({**issue, "rule": spec["id"]})
    for p in problems[:60]:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} critical-net topology violation(s)")
    return res.passed("every critical net meets its topology contract")


# ---------------------------------------------------------------------------
# connector contract
# ---------------------------------------------------------------------------

@gate("CONTRACT.CONNECTOR", "Connector mating contract is consistent everywhere",
      requires=("connector_contracts",))
def connector_contract(ctx, res):
    tokens = ctx.manifest.get("connector_gender_tokens")
    doc_texts = _docs(ctx, ctx.manifest.get("documentation_globs"))
    board = ctx.board()
    problems = []
    for spec in ctx.manifest.get("connector_contracts"):
        rule = ConnectorContractRule(spec, tokens)
        issues, facts = rule.evaluate(board, doc_texts)
        res.measurements[spec["id"]] = facts
        for issue in issues:
            problems.append({**issue, "contract": spec["id"]})
    for p in problems[:60]:
        res.finding(**p)
    if problems:
        kinds = Counter(p["issue"] for p in problems)
        return res.failed("; ".join(f"{v}x {k}" for k, v in kinds.most_common()))
    return res.passed("every connector matches its contract in board, model and docs")


# ---------------------------------------------------------------------------
# placement contract
# ---------------------------------------------------------------------------

@gate("CONTRACT.PLACEMENT", "Component placement and orientation contracts",
      requires=("placement_rules",))
def placement_contract(ctx, res):
    origin = ctx.manifest.get("board_origin_mm")
    board = ctx.board()
    problems = []
    for spec in ctx.manifest.get("placement_rules"):
        rule = PlacementRule(spec)
        measured, issues = rule.evaluate(board, origin)
        radii = [m["radius_mm"] for m in measured]
        res.measurements[spec["id"]] = {
            "members": len(measured),
            "radius_min_mm": min(radii) if radii else None,
            "radius_max_mm": max(radii) if radii else None,
        }
        for issue in issues:
            problems.append({**issue, "rule": spec["id"]})
    for p in problems[:60]:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} placement contract violation(s)")
    return res.passed("every placement contract holds")


# ---------------------------------------------------------------------------
# BOM / CPL parity with the native board
# ---------------------------------------------------------------------------

@gate("BOM.NATIVE_PARITY", "Packaged BOM/CPL derive from the native board",
      requires=("artifacts.bom", "artifacts.cpl"))
def bom_parity(ctx, res):
    import pcbnew
    bom_path = ctx.manifest.resolve(ctx.manifest.get("artifacts.bom"))
    cpl_path = ctx.manifest.resolve(ctx.manifest.get("artifacts.cpl"))
    for p in (bom_path, cpl_path):
        if not os.path.isfile(p):
            return res.errored(f"missing packaged artifact: {p}")
        res.evidence_file(p)
    fields = ctx.manifest.get("artifacts.cpl_fields")
    board = ctx.board()

    native = {}
    for fp in board.Footprints():
        if fp.IsExcludedFromBOM() or fp.IsDNP():
            continue
        pos = fp.GetPosition()
        native[fp.GetReference()] = {
            "value": fp.GetValue(),
            "footprint": fp.GetFPIDAsString(),
            "side": "Bottom" if fp.IsFlipped() else "Top",
            "x_mm": round(pos.x / 1e6, 4),
            "y_mm": round(-pos.y / 1e6, 4),
            "rotation": round(fp.GetOrientationDegrees() % 360.0, 4),
        }
    packaged = {}
    with open(cpl_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            packaged[row[fields["designator"]]] = row
    res.measurements["native_populated"] = len(native)
    res.measurements["packaged_placements"] = len(packaged)

    problems = []
    for ref in sorted(set(native) | set(packaged)):
        if ref not in packaged:
            problems.append({"reference": ref, "issue": "populated on the board but "
                                                        "absent from the CPL"})
            continue
        if ref not in native:
            problems.append({"reference": ref, "issue": "in the CPL but not populated "
                                                        "on the board"})
            continue
        want, got = native[ref], packaged[ref]
        if got[fields["side"]].strip().lower() != want["side"].lower():
            problems.append({"reference": ref, "issue": "side mismatch",
                             "native": want["side"], "packaged": got[fields["side"]]})
        for axis, key in (("x_mm", "x"), ("y_mm", "y")):
            try:
                delta = abs(float(got[fields[key]]) - want[axis])
            except (KeyError, ValueError):
                problems.append({"reference": ref, "issue": f"unparseable {key}"})
                continue
            if delta > ctx.manifest.get("artifacts.position_tolerance_mm"):
                problems.append({"reference": ref, "issue": f"{key} mismatch",
                                 "native_mm": want[axis], "packaged": got[fields[key]],
                                 "delta_mm": round(delta, 4)})
        try:
            rot = float(got[fields["rotation"]]) % 360.0
            if abs(((rot - want["rotation"] + 180) % 360) - 180) > 0.1:
                problems.append({"reference": ref, "issue": "rotation mismatch",
                                 "native_deg": want["rotation"], "packaged": rot})
        except (KeyError, ValueError):
            problems.append({"reference": ref, "issue": "unparseable rotation"})
    for p in problems[:60]:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} BOM/CPL disagreements with the native board")
    return res.passed(f"all {len(native)} populated parts agree between the native "
                      f"board and the packaged CPL")


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------

@gate("ARCH.CONTENTS", "Production archive contains only approved fabrication data",
      requires=("archive.zip", "archive.allow"))
def archive_contents(ctx, res):
    zpath = ctx.manifest.resolve(ctx.manifest.get("archive.zip"))
    if not os.path.isfile(zpath):
        return res.errored(f"archive not found: {zpath}")
    res.evidence_file(zpath)
    allow = ctx.manifest.get("archive.allow")
    deny = ctx.manifest.get("archive.deny", [])
    res.limit("allow", allow, ctx.manifest.source_of("archive.allow"))

    problems = []
    seen = Counter()
    with zipfile.ZipFile(zpath) as zf:
        names = sorted(zf.namelist())
        res.measurements["entries"] = len(names)
        for name in names:
            data = zf.read(name)
            kind, function, empty = _classify(name, data)
            seen[function] += 1
            rule = next((a for a in allow if a["file_function"] == function), None)
            banned = next((d for d in deny if d["file_function"] == function), None)
            if banned:
                problems.append({"entry": name, "file_function": function,
                                 "issue": banned["reason"]})
                continue
            if rule is None:
                problems.append({"entry": name, "file_function": function,
                                 "issue": "file function is not on the allowlist"})
                continue
            if rule.get("require_payload", False) and empty:
                problems.append({"entry": name, "file_function": function,
                                 "issue": "layer is present but carries no geometry"})
    for rule in allow:
        need = rule.get("min_count")
        if need is not None and seen[rule["file_function"]] < need:
            problems.append({"file_function": rule["file_function"],
                             "issue": "required artifact missing from the archive",
                             "expected_min": need, "found": seen[rule["file_function"]]})
    res.measurements["by_function"] = dict(seen)
    for p in problems[:60]:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} archive content problem(s)")
    return res.passed("archive contains exactly the approved fabrication artifacts")


def _classify(name, data):
    """Identify an archive entry by content, never by filename."""
    text = data.decode("utf-8", errors="ignore")
    if text.lstrip().startswith("M48") or "\nM48" in text[:200]:
        m = re.search(r"TF\.FileFunction,([^\r\n*]+)", text)
        fn = (m.group(1) if m else "Drill,Unknown").strip()
        plated = fn.split(",")[0].lower()
        return "drill", f"Drill/{plated}", not re.search(r"^X-?[\d.]+Y", text, re.M)
    if "%FSLA" in text or "%MOMM" in text:
        m = re.search(r"%TF\.FileFunction,([^*]+)\*%", text)
        fn = (m.group(1) if m else "Unknown").strip()
        has_geometry = bool(re.search(r"D0?[13]\*", text))
        return "gerber", fn, not has_geometry
    if name.lower().endswith(".gbrjob") or '"GeneralSpecs"' in text:
        return "job", "JobFile", not text.strip()
    return "other", f"Unclassified:{os.path.splitext(name)[1] or 'none'}", not data


@gate("ARCH.PROVENANCE", "Archive and packaged artifacts share one source revision",
      requires=("archive.manifest",))
def archive_provenance(ctx, res):
    mpath = ctx.manifest.resolve(ctx.manifest.get("archive.manifest"))
    if not os.path.isfile(mpath):
        return res.errored(f"release manifest not found: {mpath}")
    res.evidence_file(mpath)
    required = ctx.manifest.get("archive.manifest_required_fields")
    res.limit("required_fields", required,
              ctx.manifest.source_of("archive.manifest_required_fields"))
    text = open(mpath, encoding="utf-8", errors="ignore").read()
    missing = [f for f in required if f.lower() not in text.lower()]
    problems = [{"field": f, "issue": "release manifest records no such provenance"}
                for f in missing]

    # Recorded hashes must still match the files they describe.
    base = os.path.dirname(mpath)
    stale = []
    for m in re.finditer(r"`([^`]+)`\s*sha256\s*`([0-9a-f]{64})`", text):
        name, digest = m.group(1), m.group(2)
        for cand in (os.path.join(base, name),
                     ctx.manifest.resolve(name),
                     os.path.join(base, os.path.basename(name))):
            if os.path.isfile(cand):
                actual = sha256_file(cand)
                if actual != digest:
                    stale.append({"artifact": name, "issue": "recorded hash no longer "
                                                             "matches the file",
                                  "recorded": digest[:16], "actual": actual[:16]})
                break
    problems += stale
    res.measurements["hashes_checked"] = len(re.findall(r"sha256\s*`[0-9a-f]{64}`", text))
    for p in problems[:40]:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} release-provenance problem(s)")
    return res.passed("release manifest records full provenance and every hash matches")


# ---------------------------------------------------------------------------
# constraint / checker parity
# ---------------------------------------------------------------------------

@gate("CFG.THRESHOLD_PARITY", "Every gate limit came from the canonical manifest",
      requires=("constraint_parity",), order=900)
def threshold_parity(ctx, res):
    """Compare each limit a gate applied against the manifest value at that key."""
    applied = ctx.cache("applied_limits", dict)
    res.measurements["limits_applied"] = len(applied)
    problems = []
    for name, record in applied.items():
        source = record.get("source", "")
        m = re.match(r"^[^#]+#([^@]+)@", source)
        if not m:
            problems.append({"limit": name, "issue": "limit has no manifest provenance",
                             "source": source})
            continue
        key = m.group(1)
        if not ctx.manifest.has(key):
            problems.append({"limit": name, "key": key,
                             "issue": "limit cites a manifest key that does not exist"})
            continue
        canonical = ctx.manifest.get(key)
        if _leaf(record["value"]) != _leaf(canonical):
            problems.append({"limit": name, "key": key,
                             "issue": "gate applied a value that is not the manifest value",
                             "applied": record["value"], "manifest": canonical})
    for p in problems:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} gate limit(s) diverge from the manifest")
    return res.passed(f"all {len(applied)} applied limits trace to the manifest")


def _leaf(value):
    if isinstance(value, list):
        return [_leaf(v) for v in value]
    if isinstance(value, dict):
        return {k: _leaf(v) for k, v in sorted(value.items())}
    return value


@gate("CFG.NO_RIVAL_THRESHOLDS", "No checker outside the manifest defines its own limits",
      requires=("constraint_parity.rival_scan",))
def rival_thresholds(ctx, res):
    spec = ctx.manifest.get("constraint_parity.rival_scan")
    root = ctx.manifest.resolve(".")
    watched = spec["watched_constants"]
    res.limit("watched_constants", watched, ctx.manifest.source_of(
        "constraint_parity.rival_scan.watched_constants"))
    problems = []
    for pat in spec["files"]:
        for path in sorted(glob.glob(os.path.join(root, pat), recursive=True)):
            rel = os.path.relpath(path, root).replace("\\", "/")
            try:
                source = open(path, encoding="utf-8", errors="ignore").read()
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    entry = watched.get(target.id)
                    if entry is None:
                        continue
                    try:
                        value = ast.literal_eval(node.value)
                    except ValueError:
                        continue
                    canonical = ctx.manifest.get(entry["manifest_key"])
                    if _leaf(value) != _leaf(canonical):
                        problems.append({
                            "file": rel, "line": node.lineno, "constant": target.id,
                            "declares": value, "manifest_key": entry["manifest_key"],
                            "manifest_value": canonical,
                            "issue": "a second, divergent copy of a canonical limit"})
    for p in problems:
        res.finding(**p)
    if problems:
        return res.failed(f"{len(problems)} rival threshold definition(s) outside "
                          f"the canonical manifest")
    return res.passed("no rival threshold definitions found")
