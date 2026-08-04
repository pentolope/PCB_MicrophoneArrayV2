"""KiCad ERC/DRC report readers.

KiCad 10 does not use one shape for both reports:

  DRC  top-level `violations`, `unconnected_items`, `schematic_parity`
  ERC  no top-level `violations` at all - findings live under
       `sheets[].violations`, one entry per sheet

Reading `doc["violations"]` for ERC therefore always yields an empty list and
the gate passes no matter what the schematic contains. That was a real
false-PASS in the previous implementation, so this module validates the shape
before trusting it and refuses to guess.

Both reports also carry `ignored_checks` (rules the run did not evaluate) and
`included_severities` (which severities the run asked for). A report that
skipped severities, or silently ignored rules, is not evidence of a clean
design and is treated as such.
"""

from __future__ import annotations


class ReportSchemaError(Exception):
    pass


REQUIRED_COMMON = ("$schema", "date", "kicad_version", "source",
                   "ignored_checks", "included_severities")

DRC_BUCKETS = ("violations", "unconnected_items", "schematic_parity")


def _require(doc, keys, kind):
    missing = [k for k in keys if k not in doc]
    if missing:
        raise ReportSchemaError(
            f"{kind} report is missing {missing}; this validator implements the "
            f"KiCad 10 report schema and will not guess at an unknown one")


def parse_drc(doc):
    _require(doc, REQUIRED_COMMON, "DRC")
    _require(doc, DRC_BUCKETS, "DRC")
    findings = []
    for bucket in DRC_BUCKETS:
        items = doc.get(bucket)
        if not isinstance(items, list):
            raise ReportSchemaError(f"DRC report `{bucket}` is not a list")
        for item in items:
            findings.append(_normalise(item, bucket))
    return findings, _meta(doc)


def parse_erc(doc):
    _require(doc, REQUIRED_COMMON, "ERC")
    if "sheets" not in doc:
        raise ReportSchemaError(
            "ERC report has no `sheets`; KiCad 10 reports ERC findings per sheet")
    if "violations" in doc:
        raise ReportSchemaError(
            "ERC report has an unexpected top-level `violations`; the schema this "
            "validator implements puts them under sheets[].violations")
    findings = []
    for sheet in doc["sheets"]:
        if not isinstance(sheet, dict) or "violations" not in sheet:
            raise ReportSchemaError("ERC sheet entry has no `violations` list")
        for item in sheet["violations"]:
            entry = _normalise(item, "violations")
            entry["sheet"] = sheet.get("path") or sheet.get("uuid_path")
            findings.append(entry)
    return findings, _meta(doc)


def _normalise(item, bucket):
    first = (item.get("items") or [{}])[0]
    pos = first.get("pos") or {}
    return {
        "category": bucket,
        "severity": item.get("severity"),
        "rule": item.get("type"),
        "description": (item.get("description") or "")[:200],
        "object": (first.get("description") or "")[:160],
        "x_mm": pos.get("x"),
        "y_mm": pos.get("y"),
    }


def _meta(doc):
    return {
        "schema": doc.get("$schema"),
        "date": doc.get("date"),
        "kicad_version": doc.get("kicad_version"),
        "source": doc.get("source"),
        "ignored_checks": [c.get("key") for c in doc.get("ignored_checks") or []],
        "included_severities": doc.get("included_severities") or [],
        "coordinate_units": doc.get("coordinate_units"),
    }
