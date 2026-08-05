"""Provenance, source authority and authoritative ERC/DRC gates.

Generic: every path, rule name, tolerance and claim pattern comes from the
manifest.
"""

from __future__ import annotations

import glob
import json
import os
import re

from ..core import Status, gate, sha256_file


# ---------------------------------------------------------------------------
# source-of-truth authority
# ---------------------------------------------------------------------------

@gate("PROV.SOURCE_AUTHORITY", "KiCad is the sole design authority",
      requires=("source_authority",))
def source_authority(ctx, res):
    policy = ctx.manifest.get("source_authority")
    root = ctx.manifest.resolve(".")
    res.limit(ctx.manifest.constraint("source_authority.authority",
                                      units="policy", cid="source_authority"))

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
      requires=("reports", "reports.source_closure",
                "fixture.attributes_file"))
def report_freshness(ctx, res):
    """A report is fresh only if the inputs it was made from still hash the same.

    Timestamps prove nothing: a file can be touched, and a report can be newer
    than a source it never saw. So the gate recomputes the canonical digest of
    every input a check result depends on - the schematic and its sheets, the
    board, the project settings, the design rules and the manifest itself - and
    compares those *values* against the hashes bound into each report. A report
    that records no hashes cannot be tied to a revision and is stale by
    definition.
    """
    from .. import canonical, cleanroom

    spec = ctx.manifest.get("reports")
    root = ctx.manifest.resolve(".")
    res.limit(ctx.manifest.constraint("reports.source_closure",
                                      units="path glob",
                                      cid="reports.source_closure"))
    policy = canonical.AttributePolicy.load(
        ctx.manifest.resolve(ctx.manifest.get("fixture.attributes_file")))
    closure = cleanroom.source_closure(ctx.manifest, policy)
    closure_hash = cleanroom.closure_digest(closure)
    res.measurements["source_closure_files"] = len(closure)
    res.measurements["source_closure_sha256"] = closure_hash

    sources = {"pcb": ctx.board_path(), "schematic": ctx.schematic_path()}
    live = {k: sha256_file(v) for k, v in sources.items() if os.path.isfile(v)}
    by_basename = {os.path.basename(v): sha256_file(v)
                   for v in sources.values() if os.path.isfile(v)}
    res.measurements["source_sha256"] = {k: v[:16] for k, v in live.items()}

    hash_field = spec.get("source_hash_field", "source_sha256")
    closure_field = spec.get("closure_field", "source_closure_sha256")
    require_hash = spec.get("require_source_hash", True)

    stale = []
    examined = _expand(root, spec["files"])
    for rel in examined:
        path = os.path.join(root, rel)
        record = {"file": rel}
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except (ValueError, OSError) as exc:
            stale.append({**record, "issue": "unreadable: {}".format(exc)})
            continue
        declared = doc.get(spec.get("source_field", "source"))
        record["declares_source"] = declared
        record["date"] = doc.get(spec.get("date_field", "date"))
        declared_base = os.path.basename(str(declared)) if declared else None
        if declared and declared_base not in by_basename:
            stale.append({**record,
                          "issue": "declares a source file that is not a current "
                                   "design source"})
            continue

        recorded = doc.get(hash_field)
        if not recorded:
            if require_hash:
                stale.append({**record,
                              "issue": "records no source hash, so it cannot be "
                                       "tied to a specific revision"})
            continue
        expected = by_basename.get(declared_base)
        if expected is None:
            stale.append({**record,
                          "issue": "records a source hash but names no source it "
                                   "can be checked against"})
            continue
        if recorded != expected:
            stale.append({**record, "issue": "source hash bound into the report "
                                             "does not match the current source",
                          "recorded": recorded[:16], "recomputed": expected[:16]})
            continue

        recorded_closure = doc.get(closure_field)
        if not recorded_closure:
            stale.append({**record,
                          "issue": "records no source-closure hash, so a change to "
                                   "the project settings or design rules would "
                                   "leave it looking fresh"})
            continue
        if recorded_closure != closure_hash:
            entry = {**record,
                     "issue": "source closure changed since the report was made",
                     "recorded": str(recorded_closure)[:16],
                     "recomputed": closure_hash[:16]}
            bound = doc.get("source_closure")
            if isinstance(bound, dict):
                changed = sorted(k for k in set(bound) & set(closure)
                                 if bound[k] != closure[k])
                entry["changed_inputs"] = changed[:8]
                entry["added_inputs"] = sorted(set(closure) - set(bound))[:8]
                entry["removed_inputs"] = sorted(set(bound) - set(closure))[:8]
            stale.append(entry)

    for s_ in stale:
        res.finding(**s_)
    res.measurements["reports_examined"] = len(examined)
    if stale:
        return res.failed("{} committed report(s) cannot be tied to the current "
                          "sources".format(len(stale)))
    return res.passed(
        "every committed report binds the canonical digest of all {} source "
        "inputs, and every one still matches".format(len(closure)))
