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

import fnmatch
import hashlib
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
    """An exact inventory, not a spot check.

    Every recorded file must be present, of the recorded classification and of
    the recorded canonical digest; and every file present must be recorded. An
    unrecorded file is as much a change to the frozen copy as an edited one -
    it is how a stray export, an editor backup or a lock file gets in. Anything
    that is not a regular file (a symlink, a device node, a junction) fails
    outright: the digest of a link says nothing about what it points at.
    """
    hash_file = ctx.manifest.resolve(ctx.manifest.get("fixture.hash_file"))
    res.evidence_file(hash_file)
    meta = json.load(open(hash_file, encoding="utf-8"))
    policy_path = ctx.manifest.resolve(ctx.manifest.get("fixture.attributes_file"))
    policy = canonical.AttributePolicy.load(policy_path)
    reject = res.limit(ctx.manifest.constraint(
        "fixture.reject_globs", units="path glob",
        cid="fixture.reject_globs")).value
    res.measurements["digest_policy"] = meta.get("digest_policy")
    res.measurements["normalization_commit"] = meta.get("normalization_commit")
    res.measurements["files_recorded"] = len(meta["files"])

    base = os.path.join(os.path.dirname(hash_file), "project")
    changed, missing, reclassified, extra, badtype, rejected = [], [], [], [], [], []

    present = set()
    for dirpath, dirs, names in os.walk(base):
        for name in sorted(dirs):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                badtype.append({"file": os.path.relpath(full, base).replace(
                    "\\", "/"), "issue": "directory symlink in the frozen copy"})
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base).replace("\\", "/")
            present.add(rel)
            if os.path.islink(full):
                badtype.append({"file": rel, "issue": "symbolic link, not a file"})
            elif not os.path.isfile(full):
                badtype.append({"file": rel, "issue": "not a regular file"})
            if _matches_any(rel, reject):
                rejected.append({"file": rel,
                                 "issue": "lock or scratch file has no place in a "
                                          "frozen design copy"})

    for rel, record in meta["files"].items():
        path = os.path.join(base, rel)
        if not os.path.isfile(path) or os.path.islink(path):
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

    for rel in sorted(present - set(meta["files"])):
        extra.append({"file": rel,
                      "issue": "present in the frozen copy but not in the "
                               "inventory; the frozen set is exact"})

    res.measurements["files_present"] = len(present)
    for entry in changed + reclassified + extra + badtype + rejected:
        res.finding(**entry)
    for rel in missing:
        res.finding(file=rel, issue="missing from frozen copy")
    total = len(changed) + len(missing) + len(reclassified) + len(extra) \
        + len(badtype) + len(rejected)
    if total:
        return res.failed(
            "frozen fixture altered: {} changed, {} missing, {} extra, {} "
            "reclassified, {} not a regular file, {} rejected by policy".format(
                len(changed), len(missing), len(extra), len(reclassified),
                len(badtype), len(rejected)))
    return res.passed(
        "the frozen copy holds exactly the {} recorded files, each a regular "
        "file matching its canonical digest (text hashed over LF bytes, "
        "production output over raw bytes)".format(len(meta["files"])))


def _matches_any(rel, patterns):
    name = os.path.basename(rel)
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p)
               for p in patterns)


# ---------------------------------------------------------------------------
# ERC / DRC
# ---------------------------------------------------------------------------

WAIVER_REQUIRED_FIELDS = ("gate", "rule", "category", "objects", "location_mm",
                          "reason", "reviewed_by", "reviewed_utc",
                          "approved_source_sha256", "approved_rules_sha256",
                          "approved_command_sha256", "approved_report_sha256")


def _canonical_command(args):
    """The command, with absolute paths reduced to basenames.

    A waiver must not stop matching because the checkout moved, but it must
    stop matching if an option changed - the options are what decide which
    checks ran at all.
    """
    return " ".join(os.path.basename(a) if os.path.sep in a else a for a in args)


def _finding_key(f):
    return {
        "category": f.get("category"), "rule": f.get("rule"),
        "severity": f.get("severity"), "objects": sorted(f.get("objects") or []),
        "x_mm": f.get("x_mm"), "y_mm": f.get("y_mm"),
        "description": f.get("description"),
    }


def _report_digest(findings):
    """A digest of what the reviewer actually saw.

    Deliberately not the digest of the report file: KiCad stamps a timestamp
    into every report, so a file digest would expire a waiver on every run and
    teach people to disable it. This digest covers the findings themselves, so
    it survives a re-run of an unchanged design and changes the moment a new
    finding appears or an existing one moves.
    """
    payload = json.dumps(sorted((json.dumps(_finding_key(f), sort_keys=True)
                                 for f in findings)), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _waiver_defects(w, tol):
    """Why a waiver record cannot be honoured. Empty means it is well formed."""
    bad = []
    for field in WAIVER_REQUIRED_FIELDS:
        if w.get(field) in (None, "", [], {}):
            bad.append("waiver omits {!r}".format(field))
    objects = w.get("objects")
    if objects is not None and (not isinstance(objects, list)
                                or not all(isinstance(o, str) and o.strip()
                                           for o in objects)):
        bad.append("waiver `objects` must be a non-empty list of object "
                   "descriptions; a waiver that names no object is a blanket "
                   "waiver")
    loc = w.get("location_mm")
    if loc is not None and (not isinstance(loc, (list, tuple)) or len(loc) != 2
                            or not all(isinstance(v, (int, float)) for v in loc)):
        bad.append("waiver `location_mm` must be an [x, y] pair in mm")
    for field in ("rule", "category"):
        value = w.get(field)
        if isinstance(value, str) and value.strip() in ("*", "any", "all"):
            bad.append("waiver {!r} is a wildcard; waivers are exact".format(field))
    if tol is None:
        bad.append("no location tolerance is declared for waiver matching")
    return bad


def _waivers_for(ctx, gate_id, bindings, tol):
    """Waivers that are well formed, for this gate, and still bound to reality."""
    live, rejected = [], []
    for w in ctx.manifest.get("waivers", []):
        if w.get("gate") != gate_id:
            continue
        defects = _waiver_defects(w, tol)
        if defects:
            rejected.append({"waiver": w.get("id") or w.get("rule"),
                             "issue": "; ".join(defects)})
            continue
        stale = [name for name, current in bindings.items()
                 if w.get(name) != current]
        if stale:
            rejected.append({
                "waiver": w.get("id") or w.get("rule"),
                "issue": "waiver was approved against different inputs and no "
                         "longer applies",
                "changed": sorted(stale)})
            continue
        live.append(w)
    return live, rejected


def _waived(finding, waivers, tol):
    """Exact match only: same rule, same category, same objects, same place."""
    for w in waivers:
        if w["rule"] != finding.get("rule"):
            continue
        if w["category"] != finding.get("category"):
            continue
        if sorted(w["objects"]) != sorted(finding.get("objects") or []):
            continue
        x, y = finding.get("x_mm"), finding.get("y_mm")
        if x is None or y is None:
            continue
        wx, wy = w["location_mm"]
        if abs(x - wx) > tol or abs(y - wy) > tol:
            continue
        return w
    return None


def _run(ctx, res, kind, gate_id):
    spec = ctx.manifest.get("checks.{}".format(kind))
    source = ctx.schematic_path() if kind == "erc" else ctx.board_path()
    source_hash = sha256_file(source)
    rules_hash = (sha256_file(ctx.project_path())
                  if os.path.isfile(ctx.project_path()) else None)

    required_flags = res.limit(ctx.manifest.constraint(
        "checks.{}.required_flags".format(kind), units="cli option",
        cid="checks.{}.required_flags".format(kind))).value
    required_sev = res.limit(ctx.manifest.constraint(
        "checks.{}.required_severities".format(kind), units="severity",
        cid="checks.{}.required_severities".format(kind))).value
    violations_exit = res.limit(ctx.manifest.constraint(
        "checks.{}.violations_exit_code".format(kind), units="exit status",
        cid="checks.{}.violations_exit_code".format(kind))).value
    waiver_tol = res.limit(ctx.manifest.geometry_profile()
                           .tolerance("waiver_location_mm")).value

    out_json = os.path.join(ctx.workdir, "{}_authoritative.json".format(kind))
    args = [ctx.kicad_cli, ("sch" if kind == "erc" else "pcb"), kind,
            "--format", "json", "-o", out_json] \
        + list(spec.get("flags", [])) + [source]
    command = _canonical_command(args)
    command_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()

    try:
        proc = ctx.run_tool(args)
    except Exception as exc:                    # timeout, missing binary, ...
        return res.errored(
            "{} could not be invoked: {}: {}".format(kind.upper(),
                                                     type(exc).__name__, exc))

    res.measurements.update({
        "command": command,
        "command_sha256": command_hash,
        "exit_status": proc.returncode,
        "violations_exit_code": violations_exit,
        "source": os.path.basename(source),
        "source_sha256": source_hash,
        "rules_sha256": rules_hash,
        "constraint_manifest_sha256": ctx.manifest.sha256,
        "kicad_version": ctx.kicad_version(),
        "generated_utc": utcnow(),
    })

    # A tool that could not do its job is an ERROR, never a FAIL: "the design
    # is bad" and "we do not know whether the design is bad" are different
    # answers, and only one of them can be argued with.
    if proc.returncode not in (0, violations_exit):
        return res.errored(
            "{} invocation failed with exit {} (documented codes: 0=clean, "
            "{}=violations found): {}".format(
                kind.upper(), proc.returncode, violations_exit,
                (proc.stderr or "").strip()[:300]))
    if not os.path.isfile(out_json):
        return res.errored(
            "{} exited {} but produced no report at all: {}".format(
                kind.upper(), proc.returncode, (proc.stderr or "").strip()[:300]))
    res.evidence_file(out_json)
    try:
        doc = json.load(open(out_json, encoding="utf-8"))
    except ValueError as exc:
        return res.errored("{} report is not readable JSON: {}".format(
            kind.upper(), exc))
    try:
        findings, meta = (reports.parse_erc(doc) if kind == "erc"
                          else reports.parse_drc(doc))
    except reports.ReportSchemaError as exc:
        return res.errored("unsupported {} report schema: {}".format(
            kind.upper(), exc))

    report_hash = _report_digest(findings)
    res.measurements["report_meta"] = meta
    res.measurements["report_findings_sha256"] = report_hash

    missing_flags = [f for f in required_flags if f not in args]
    problems = []
    if missing_flags:
        problems.append({"issue": "required command-line option not used",
                         "missing": missing_flags})
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
    if proc.returncode == violations_exit and not findings:
        problems.append({"issue": "KiCad reported violations by exit code but the "
                                  "report lists none",
                         "exit_status": proc.returncode})

    bindings = {
        "approved_source_sha256": source_hash,
        "approved_rules_sha256": rules_hash,
        "approved_command_sha256": command_hash,
        "approved_report_sha256": report_hash,
    }
    waivers, rejected = _waivers_for(ctx, gate_id, bindings, waiver_tol)
    problems.extend(rejected)

    waived = 0
    counts = {}
    used = []
    for f in findings:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
        match = _waived(f, waivers, waiver_tol)
        if match:
            waived += 1
            used.append({"rule": f["rule"], "reviewed_by": match["reviewed_by"]})
            continue
        problems.append(f)
    res.measurements["counts"] = counts
    res.measurements["waived"] = waived
    res.measurements["waivers_live"] = len(waivers)
    res.measurements["waivers_rejected"] = len(rejected)
    res.measurements["waivers_used"] = used

    for p in problems[:200]:
        res.finding(**p)
    if problems:
        return res.failed(
            "{} blocking {} condition(s); findings={}, exit={}, "
            "ignored_checks={}".format(len(problems), kind.upper(),
                                       counts or 0, proc.returncode,
                                       len(meta["ignored_checks"])))
    return res.passed(
        "{} clean: exit {}, schema validated, no ignored checks, severities {}, "
        "source {}".format(kind.upper(), proc.returncode,
                           meta["included_severities"], source_hash[:12]))


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
