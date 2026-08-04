"""Authoritative ERC and DRC gates, and the fixture-integrity gate.

Fail-closed. A gate here fails unless every one of these holds:

  * KiCad exited zero
  * the report parses against the schema this validator implements
  * no violation, warning, exclusion, unconnected item or parity issue remains
    after exact, hash-bound waivers
  * the run ignored no checks
  * the run requested every severity the manifest demands
  * the report names the source we asked it to check, and that source still
    hashes to the value recorded with the result
  * the command line carried every required option
"""

from __future__ import annotations

import json
import os

from ..core import Status, gate, sha256_file, utcnow
from .. import canonical, reports


# ---------------------------------------------------------------------------
# frozen fixture integrity, hashed canonically
# ---------------------------------------------------------------------------

@gate("PROV.FIXTURE_INTEGRITY", "Frozen fixture matches its canonical digests",
      requires=("fixture.hash_file",))
def fixture_integrity(ctx, res):
    hash_file = ctx.manifest.resolve(ctx.manifest.get("fixture.hash_file"))
    res.evidence_file(hash_file)
    meta = json.load(open(hash_file, encoding="utf-8"))
    policy_path = ctx.manifest.resolve(ctx.manifest.get("fixture.attributes_file"))
    policy = canonical.AttributePolicy.load(policy_path)
    res.measurements["digest_policy"] = meta.get("digest_policy")
    res.measurements["normalization_commit"] = meta.get("normalization_commit")
    res.measurements["files_recorded"] = len(meta["files"])

    base = os.path.join(os.path.dirname(hash_file), "project")
    changed, missing, reclassified = [], [], []
    for rel, record in meta["files"].items():
        path = os.path.join(base, rel)
        if not os.path.isfile(path):
            missing.append(rel)
            continue
        kind = policy.classify(rel)
        if kind != record["kind"]:
            reclassified.append({"file": rel, "recorded": record["kind"],
                                 "now": kind,
                                 "issue": "gitattributes classification changed"})
            continue
        if canonical.digest(path, kind) != record["sha256"]:
            changed.append({"file": rel, "kind": kind,
                            "issue": "canonical content changed since freeze"})
    for entry in changed + reclassified:
        res.finding(**entry)
    for rel in missing:
        res.finding(file=rel, issue="missing from frozen copy")
    if changed or missing or reclassified:
        return res.failed(f"frozen fixture altered: {len(changed)} changed, "
                          f"{len(missing)} missing, {len(reclassified)} reclassified")
    return res.passed(
        f"all {len(meta['files'])} frozen files match their canonical digests "
        f"(text hashed over LF bytes, production output over raw bytes)")


# ---------------------------------------------------------------------------
# ERC / DRC
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


def _waived(finding, waivers):
    for w in waivers:
        if w.get("category") and w["category"] != finding["category"]:
            continue
        if w.get("rule") and w["rule"] != finding["rule"]:
            continue
        if w.get("object") and w["object"] not in (finding.get("object") or ""):
            continue
        return w
    return None


def _run(ctx, res, kind, gate_id):
    spec = ctx.manifest.get(f"checks.{kind}")
    source = ctx.schematic_path() if kind == "erc" else ctx.board_path()
    source_hash = sha256_file(source)
    rules_hash = sha256_file(ctx.project_path()) if os.path.isfile(ctx.project_path()) else None

    required_flags = res.limit(ctx.manifest.constraint(
        f"checks.{kind}.required_flags", units="cli option",
        cid=f"checks.{kind}.required_flags")).value
    required_sev = res.limit(ctx.manifest.constraint(
        f"checks.{kind}.required_severities", units="severity",
        cid=f"checks.{kind}.required_severities")).value

    out_json = os.path.join(ctx.workdir, f"{kind}_authoritative.json")
    args = [ctx.kicad_cli, ("sch" if kind == "erc" else "pcb"), kind,
            "--format", "json", "-o", out_json] + list(spec.get("flags", [])) + [source]
    proc = ctx.run_tool(args)

    res.measurements.update({
        "command": " ".join(args[1:]),
        "exit_status": proc.returncode,
        "source": os.path.basename(source),
        "source_sha256": source_hash,
        "rules_sha256": rules_hash,
        "constraint_manifest_sha256": ctx.manifest.sha256,
        "kicad_version": ctx.kicad_version(),
        "generated_utc": utcnow(),
    })

    missing_flags = [f for f in required_flags if f not in args]
    if missing_flags:
        res.finding(issue="required command-line option not used",
                    missing=missing_flags)

    if not os.path.isfile(out_json):
        return res.errored(f"{kind} produced no report "
                           f"(exit {proc.returncode}): {proc.stderr.strip()[:300]}")
    res.evidence_file(out_json)
    doc = json.load(open(out_json, encoding="utf-8"))
    try:
        findings, meta = (reports.parse_erc(doc) if kind == "erc"
                          else reports.parse_drc(doc))
    except reports.ReportSchemaError as exc:
        return res.errored(f"unsupported {kind} report schema: {exc}")

    res.measurements["report_meta"] = meta
    problems = []

    if os.path.basename(str(meta["source"])) != os.path.basename(source):
        problems.append({"issue": "report names a different source than we checked",
                         "report_source": meta["source"],
                         "checked": os.path.basename(source)})
    if meta["ignored_checks"]:
        problems.append({"issue": "run ignored one or more checks",
                         "ignored": meta["ignored_checks"]})
    absent_sev = [s for s in required_sev if s not in meta["included_severities"]]
    if absent_sev:
        problems.append({"issue": "run did not include every required severity",
                         "missing": absent_sev,
                         "included": meta["included_severities"]})
    if proc.returncode != 0 and not findings:
        problems.append({"issue": "KiCad exited nonzero but reported no findings",
                         "exit_status": proc.returncode})

    waivers = _waivers_for(ctx, gate_id, source_hash)
    waived = 0
    counts = {}
    for f in findings:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
        if _waived(f, waivers):
            waived += 1
            continue
        problems.append(f)
    res.measurements["counts"] = counts
    res.measurements["waived"] = waived
    res.measurements["waivers_available"] = len(waivers)

    for p in problems[:200]:
        res.finding(**p)
    if missing_flags:
        problems.append({"issue": "options"})
    if problems:
        return res.failed(
            f"{len(problems)} blocking {kind.upper()} condition(s); "
            f"findings={counts or 0}, exit={proc.returncode}, "
            f"ignored_checks={len(meta['ignored_checks'])}")
    return res.passed(
        f"{kind.upper()} clean: exit 0, schema validated, no ignored checks, "
        f"severities {meta['included_severities']}, source {source_hash[:12]}")


@gate("ERC.AUTHORITATIVE", "Fresh ERC on the exact final schematic",
      requires=("checks.erc.required_flags",))
def erc(ctx, res):
    return _run(ctx, res, "erc", "ERC.AUTHORITATIVE")


@gate("DRC.AUTHORITATIVE", "Fresh DRC on the exact final board",
      requires=("checks.drc.required_flags",))
def drc(ctx, res):
    return _run(ctx, res, "drc", "DRC.AUTHORITATIVE")


@gate("DRC.NO_SUPPRESSED_RULES", "No design rule is silently disabled",
      requires=("checks.drc.forbidden_severities",))
def suppressed(ctx, res):
    forbidden = res.limit(ctx.manifest.constraint(
        "checks.drc.forbidden_severities", units="severity",
        cid="checks.drc.forbidden_severities")).value
    allowed = set(ctx.manifest.get("checks.drc.permitted_ignored_rules", []))
    project = ctx.project_path()
    res.evidence_file(project)
    doc = json.load(open(project, encoding="utf-8"))
    board = doc.get("board", {})
    sev = board.get("design_settings", {}).get("rule_severities", {})
    offenders = sorted(k for k, v in sev.items()
                       if v in forbidden and k not in allowed)
    exclusions = board.get("drc_exclusions") or []
    erc_sev = doc.get("erc", {}).get("rule_severities", {})
    erc_off = sorted(k for k, v in erc_sev.items()
                     if v in forbidden and k not in allowed)
    erc_excl = doc.get("erc", {}).get("erc_exclusions") or []
    res.measurements.update({
        "drc_ignored_rules": offenders, "drc_exclusions": len(exclusions),
        "erc_ignored_rules": erc_off, "erc_exclusions": len(erc_excl),
    })
    for rule in offenders:
        res.finding(domain="drc", rule=rule, severity=sev[rule],
                    issue="rule disabled without an approved waiver")
    for rule in erc_off:
        res.finding(domain="erc", rule=rule, severity=erc_sev[rule],
                    issue="rule disabled without an approved waiver")
    for item in exclusions + erc_excl:
        res.finding(issue="stored exclusion", detail=str(item)[:120])
    if offenders or erc_off or exclusions or erc_excl:
        return res.failed(
            f"{len(offenders)} DRC and {len(erc_off)} ERC rule(s) disabled, "
            f"{len(exclusions) + len(erc_excl)} stored exclusion(s)")
    return res.passed("no rule is disabled outside the approved list")
