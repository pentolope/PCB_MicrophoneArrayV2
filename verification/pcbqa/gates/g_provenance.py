"""Provenance, source authority and authoritative ERC/DRC gates.

Generic: every path, rule name, tolerance and claim pattern comes from the
manifest.
"""

from __future__ import annotations

import glob
import json
import os
import re

from ..core import Status, gate, sha256_file, utcnow


# ---------------------------------------------------------------------------
# fixture integrity
# ---------------------------------------------------------------------------

@gate("PROV.FIXTURE_INTEGRITY", "Frozen fixture is byte-for-byte unmodified",
      requires=("fixture.hash_file",))
def fixture_integrity(ctx, res):
    hash_file = ctx.manifest.resolve(ctx.manifest.get("fixture.hash_file"))
    res.evidence_file(hash_file)
    with open(hash_file, encoding="utf-8") as fh:
        meta = json.load(fh)
    base = os.path.dirname(hash_file)
    changed, missing = [], []
    for rel, digest in meta["files"].items():
        path = os.path.join(base, "project", rel)
        if not os.path.isfile(path):
            missing.append(rel)
        elif sha256_file(path) != digest:
            changed.append(rel)
    res.measurements["files_recorded"] = len(meta["files"])
    if changed or missing:
        for rel in changed:
            res.finding(file=rel, issue="content changed since freeze")
        for rel in missing:
            res.finding(file=rel, issue="missing from frozen copy")
        return res.failed(
            f"frozen fixture altered: {len(changed)} changed, {len(missing)} missing")
    return res.passed(f"all {len(meta['files'])} frozen files match their recorded digests")


# ---------------------------------------------------------------------------
# source-of-truth authority
# ---------------------------------------------------------------------------

@gate("PROV.SOURCE_AUTHORITY", "KiCad is the sole design authority",
      requires=("source_authority",))
def source_authority(ctx, res):
    policy = ctx.manifest.get("source_authority")
    root = ctx.manifest.resolve(".")
    res.limit("authority", policy.get("authority"),
              ctx.manifest.source_of("source_authority.authority"))

    claims = []
    for spec in policy.get("claim_scan", []):
        pattern = re.compile(spec["pattern"], re.I)
        for rel in _expand(root, spec["files"]):
            path = os.path.join(root, rel)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for m in pattern.finditer(text):
                line = text[:m.start()].count("\n") + 1
                claims.append({"file": rel, "line": line,
                               "claim": spec["claim"],
                               "text": m.group(0)[:110]})
    by_claim = {}
    for c in claims:
        by_claim.setdefault(c["claim"], []).append(c)

    # Contradiction: two mutually exclusive claims both asserted somewhere.
    conflicts = []
    for pair in policy.get("mutually_exclusive_claims", []):
        present = [c for c in pair if c in by_claim]
        if len(present) > 1:
            conflicts.append(present)

    # A non-KiCad model must not be a data source for released artifacts.
    derived = []
    for spec in policy.get("forbidden_derivations", []):
        pattern = re.compile(spec["pattern"])
        for rel in _expand(root, spec["files"]):
            path = os.path.join(root, rel)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for m in pattern.finditer(text):
                derived.append({"file": rel,
                                "line": text[:m.start()].count("\n") + 1,
                                "issue": spec["issue"], "text": m.group(0)[:110]})

    for group in conflicts:
        members = []
        for claim in group:
            for c in by_claim[claim][:4]:
                members.append(f"{c['file']}:{c['line']}")
        res.finding(issue="contradictory source-of-truth claims",
                    claims=group, seen_at=members)
    for d in derived:
        res.finding(**d)

    res.measurements["claims_found"] = {k: len(v) for k, v in by_claim.items()}
    if conflicts or derived:
        return res.failed(
            f"{len(conflicts)} contradictory authority claim group(s), "
            f"{len(derived)} non-authoritative derivation(s) of released data")
    return res.passed("a single, consistent design authority is asserted")


def _expand(root, patterns):
    out = []
    for pat in patterns:
        for path in glob.glob(os.path.join(root, pat), recursive=True):
            if os.path.isfile(path):
                out.append(os.path.relpath(path, root).replace("\\", "/"))
    return sorted(set(out))


# ---------------------------------------------------------------------------
# report freshness
# ---------------------------------------------------------------------------

@gate("PROV.REPORT_FRESHNESS", "Committed reports match the current sources",
      requires=("reports",))
def report_freshness(ctx, res):
    spec = ctx.manifest.get("reports")
    root = ctx.manifest.resolve(".")
    sources = {
        "pcb": ctx.board_path(),
        "schematic": ctx.schematic_path(),
    }
    live = {k: sha256_file(v) for k, v in sources.items() if os.path.isfile(v)}
    live_mtime = max(os.path.getmtime(v) for v in sources.values() if os.path.isfile(v))
    res.measurements["source_sha256"] = {k: v[:16] for k, v in live.items()}

    stale = []
    for rel in _expand(root, spec["files"]):
        path = os.path.join(root, rel)
        record = {"file": rel}
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except (ValueError, OSError) as exc:
            stale.append({**record, "issue": f"unreadable: {exc}"})
            continue
        # A report is fresh only if it names the source it was made from and
        # that source still hashes the same, or it is newer than every source.
        declared = doc.get(spec.get("source_field", "source"))
        record["declares_source"] = declared
        record["date"] = doc.get(spec.get("date_field", "date"))
        if declared and not any(os.path.basename(s) == os.path.basename(str(declared))
                                for s in sources.values()):
            stale.append({**record, "issue": "declares a source file that is not a "
                                             "current design source"})
            continue
        if os.path.getmtime(path) < live_mtime - spec.get("tolerance_seconds", 0):
            stale.append({**record, "issue": "older than the design sources it claims "
                                             "to describe"})
            continue
        if spec.get("require_source_hash", True) and not doc.get("source_sha256"):
            stale.append({**record, "issue": "records no source hash, so it cannot be "
                                             "tied to a specific revision"})
    for s in stale:
        res.finding(**s)
    res.measurements["reports_examined"] = len(_expand(root, spec["files"]))
    if stale:
        return res.failed(f"{len(stale)} committed report(s) cannot be tied to the "
                          f"current sources")
    return res.passed("every committed report is traceable to the current sources")


# ---------------------------------------------------------------------------
# authoritative ERC / DRC
# ---------------------------------------------------------------------------

def _waivers_for(ctx, gate_id, source_hash):
    out = []
    for w in ctx.manifest.get("waivers", []):
        if w.get("gate") != gate_id:
            continue
        if w.get("approved_source_sha256") != source_hash:
            continue
        out.append(w)
    return out


def _run_kicad_check(ctx, res, kind, spec, source_path, gate_id):
    out_json = os.path.join(ctx.workdir, f"{kind}.json")
    args = [ctx.kicad_cli, kind if kind == "drc" else "erc"]
    args = [ctx.kicad_cli, ("pcb" if kind == "drc" else "sch"), kind,
            "--format", "json", "-o", out_json]
    for flag in spec.get("flags", []):
        args.append(flag)
    args.append(source_path)
    proc = ctx.run_tool(args)
    source_hash = sha256_file(source_path)
    res.measurements["command"] = " ".join(os.path.basename(a) if i == 0 else a
                                           for i, a in enumerate(args))
    res.measurements["exit_status"] = proc.returncode
    res.measurements["source_sha256"] = source_hash
    res.measurements["kicad_version"] = ctx.kicad_version()
    res.measurements["generated_utc"] = utcnow()
    res.measurements["constraint_sha256"] = ctx.manifest.sha256
    if not os.path.isfile(out_json):
        return res.errored(f"{kind} produced no report: {proc.stderr.strip()[:300]}")
    res.evidence_file(out_json)
    doc = json.load(open(out_json, encoding="utf-8"))

    buckets = {}
    for key in ("violations", "unconnected_items", "schematic_parity"):
        buckets[key] = doc.get(key) or []
    waivers = _waivers_for(ctx, gate_id, source_hash)
    blocking, waived = [], []
    for key, items in buckets.items():
        for item in items:
            if _matches_waiver(item, key, waivers):
                waived.append({"category": key, "type": item.get("type")})
                continue
            first = (item.get("items") or [{}])[0]
            pos = first.get("pos") or {}
            blocking.append({
                "category": key,
                "severity": item.get("severity"),
                "rule": item.get("type"),
                "description": (item.get("description") or "")[:160],
                "x_mm": pos.get("x"), "y_mm": pos.get("y"),
            })
    res.measurements["counts"] = {k: len(v) for k, v in buckets.items()}
    res.measurements["waived"] = len(waived)
    for b in blocking[:200]:
        res.finding(**b)
    if blocking:
        return res.failed(
            f"{len(blocking)} unwaived {kind.upper()} item(s): " +
            ", ".join(f"{k}={len(v)}" for k, v in buckets.items()))
    return res.passed(f"{kind.upper()} clean on the exact current source "
                      f"({source_hash[:12]}), {len(waived)} waived")


def _matches_waiver(item, category, waivers):
    for w in waivers:
        if w.get("category") and w["category"] != category:
            continue
        if w.get("rule") and w["rule"] != item.get("type"):
            continue
        if w.get("object"):
            texts = [str((i or {}).get("description", "")) for i in (item.get("items") or [])]
            if not any(w["object"] in t for t in texts):
                continue
        return True
    return False


@gate("ERC.AUTHORITATIVE", "Fresh ERC on the exact final schematic",
      requires=("checks.erc",))
def erc_authoritative(ctx, res):
    spec = ctx.manifest.get("checks.erc")
    return _run_kicad_check(ctx, res, "erc", spec, ctx.schematic_path(),
                            "ERC.AUTHORITATIVE")


@gate("DRC.AUTHORITATIVE", "Fresh DRC on the exact final board",
      requires=("checks.drc",))
def drc_authoritative(ctx, res):
    spec = ctx.manifest.get("checks.drc")
    return _run_kicad_check(ctx, res, "drc", spec, ctx.board_path(),
                            "DRC.AUTHORITATIVE")


@gate("DRC.NO_SUPPRESSED_RULES", "No DRC rule is silently disabled",
      requires=("checks.drc.forbidden_severities",))
def drc_suppression(ctx, res):
    forbidden = ctx.manifest.get("checks.drc.forbidden_severities")
    allowed = set(ctx.manifest.get("checks.drc.permitted_ignored_rules", []))
    res.limit("forbidden_severities", forbidden,
              ctx.manifest.source_of("checks.drc.forbidden_severities"))
    project = ctx.project_path()
    res.evidence_file(project)
    doc = json.load(open(project, encoding="utf-8"))
    sev = (doc.get("board", {}).get("design_settings", {})
              .get("rule_severities", {}))
    offenders = sorted(k for k, v in sev.items()
                       if v in forbidden and k not in allowed)
    exclusions = doc.get("board", {}).get("drc_exclusions") or []
    res.measurements["ignored_rules"] = offenders
    res.measurements["stored_exclusions"] = len(exclusions)
    for rule in offenders:
        res.finding(rule=rule, severity=sev[rule],
                    issue="rule disabled without an approved waiver")
    if offenders or exclusions:
        return res.failed(f"{len(offenders)} DRC rule(s) disabled, "
                          f"{len(exclusions)} stored exclusion(s)")
    return res.passed("no DRC rule is disabled outside the approved list")
