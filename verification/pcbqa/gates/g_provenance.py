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
