"""KiCad ERC/DRC report readers.

KiCad 10 does not use one shape for both reports:

  DRC  top-level `violations`, `unconnected_items`, `schematic_parity`
  ERC  no top-level `violations` at all - findings live under
       `sheets[].violations`, one entry per sheet

Reading `doc["violations"]` for ERC therefore always yields an empty list and
the gate passes no matter what the schematic contains. That was a real
false-PASS in the previous implementation, so this module validates the shape
before trusting it and refuses to guess.

Everything here fails closed. A report is only accepted when it carries a
schema marker this reader implements, a KiCad major version whose report
structure has actually been verified, every required section, and findings that
are individually well formed. An unrecognised or damaged report raises
`ReportSchemaError`, which the gates turn into ERROR - never into a pass, and
never into a quiet "no findings".

Both reports also carry `ignored_checks` (rules the run did not evaluate) and
`included_severities` (which severities the run asked for). A report that
skipped severities, or silently ignored rules, is not evidence of a clean
design and is treated as such.
"""

from __future__ import annotations


class ReportSchemaError(Exception):
    pass


# Schema markers this reader implements. A marker outside this set means the
# file may be laid out differently in ways we cannot see, so it is refused
# rather than parsed optimistically.
SUPPORTED_SCHEMAS = {
    "ERC": ("https://schemas.kicad.org/erc.v1.json",),
    "DRC": ("https://schemas.kicad.org/drc.v1.json",),
}

# Major versions whose report structure has been verified against the real
# tool. A newer major may move findings again, exactly as KiCad 10 did.
SUPPORTED_KICAD_MAJOR = (10,)

REQUIRED_COMMON = ("$schema", "date", "kicad_version", "source",
                   "ignored_checks", "included_severities")

DRC_BUCKETS = ("violations", "unconnected_items", "schematic_parity")

KNOWN_SEVERITIES = ("error", "warning", "exclusion", "ignore", "info")


def _require(doc, keys, kind):
    missing = [k for k in keys if k not in doc]
    if missing:
        raise ReportSchemaError(
            f"{kind} report is missing {missing}; this validator implements the "
            f"KiCad 10 report schema and will not guess at an unknown one")


def _envelope(doc, kind):
    """Validate everything that is common to both report kinds."""
    if not isinstance(doc, dict):
        raise ReportSchemaError(
            f"{kind} report is a {type(doc).__name__}, not a JSON object")
    _require(doc, REQUIRED_COMMON, kind)

    marker = doc.get("$schema")
    if marker not in SUPPORTED_SCHEMAS[kind]:
        raise ReportSchemaError(
            f"{kind} report declares schema {marker!r}; this validator "
            f"implements {list(SUPPORTED_SCHEMAS[kind])} and refuses to read a "
            f"layout it has not verified")

    version = str(doc.get("kicad_version") or "")
    major = version.split(".")[0]
    if not major.isdigit() or int(major) not in SUPPORTED_KICAD_MAJOR:
        raise ReportSchemaError(
            f"{kind} report was produced by KiCad {version!r}; report structure "
            f"is version-specific and only major version(s) "
            f"{list(SUPPORTED_KICAD_MAJOR)} have been verified")

    if not isinstance(doc.get("source"), str) or not doc["source"].strip():
        raise ReportSchemaError(f"{kind} report names no source file")
    if not isinstance(doc.get("date"), str) or not doc["date"].strip():
        raise ReportSchemaError(f"{kind} report carries no date")

    ignored = doc.get("ignored_checks")
    if not isinstance(ignored, list):
        raise ReportSchemaError(f"{kind} report `ignored_checks` is not a list")
    for entry in ignored:
        if not isinstance(entry, dict) or not entry.get("key"):
            raise ReportSchemaError(
                f"{kind} report has an ignored-check entry with no key: "
                f"{entry!r}")

    severities = doc.get("included_severities")
    if not isinstance(severities, list) or not severities:
        raise ReportSchemaError(
            f"{kind} report does not say which severities it included, so it "
            f"cannot be evidence that anything was checked")
    for entry in severities:
        if not isinstance(entry, str) or entry not in KNOWN_SEVERITIES:
            raise ReportSchemaError(
                f"{kind} report includes unknown severity {entry!r}")


def parse_drc(doc):
    _envelope(doc, "DRC")
    _require(doc, DRC_BUCKETS, "DRC")
    findings = []
    for bucket in DRC_BUCKETS:
        items = doc.get(bucket)
        if not isinstance(items, list):
            raise ReportSchemaError(f"DRC report `{bucket}` is not a list")
        for item in items:
            findings.append(_normalise(item, bucket, "DRC"))
    return findings, _meta(doc)


def parse_erc(doc):
    _envelope(doc, "ERC")
    if "sheets" not in doc:
        raise ReportSchemaError(
            "ERC report has no `sheets`; KiCad 10 reports ERC findings per sheet")
    if "violations" in doc:
        raise ReportSchemaError(
            "ERC report has an unexpected top-level `violations`; the schema this "
            "validator implements puts them under sheets[].violations")
    if not isinstance(doc["sheets"], list) or not doc["sheets"]:
        raise ReportSchemaError(
            "ERC report lists no sheets at all; an empty sheet list is not the "
            "same as a schematic with no problems")
    findings = []
    for sheet in doc["sheets"]:
        if not isinstance(sheet, dict) or "violations" not in sheet:
            raise ReportSchemaError("ERC sheet entry has no `violations` list")
        if not isinstance(sheet["violations"], list):
            raise ReportSchemaError("ERC sheet `violations` is not a list")
        for item in sheet["violations"]:
            entry = _normalise(item, "violations", "ERC")
            entry["sheet"] = sheet.get("path") or sheet.get("uuid_path")
            findings.append(entry)
    return findings, _meta(doc)


def _normalise(item, bucket, kind):
    if not isinstance(item, dict):
        raise ReportSchemaError(
            f"{kind} report `{bucket}` contains a {type(item).__name__}, not an "
            f"object")
    rule = item.get("type")
    if not isinstance(rule, str) or not rule.strip():
        raise ReportSchemaError(
            f"{kind} report has a finding in `{bucket}` with no rule type; it "
            f"cannot be waived, counted or explained")
    severity = item.get("severity")
    if severity is not None and severity not in KNOWN_SEVERITIES:
        raise ReportSchemaError(
            f"{kind} finding {rule!r} has unknown severity {severity!r}")
    items = item.get("items")
    if items is None:
        items = [{}]
    if not isinstance(items, list):
        raise ReportSchemaError(
            f"{kind} finding {rule!r} has a non-list `items`")
    for sub in items:
        if not isinstance(sub, dict):
            raise ReportSchemaError(
                f"{kind} finding {rule!r} names a non-object affected item")
    if not items:
        items = [{}]

    first = items[0]
    pos = first.get("pos") or {}
    if pos and not isinstance(pos, dict):
        raise ReportSchemaError(
            f"{kind} finding {rule!r} has a malformed position")
    return {
        "category": bucket,
        "severity": severity,
        "rule": rule,
        "description": (item.get("description") or "")[:200],
        "object": (first.get("description") or "")[:160],
        # Every affected object, not just the first: a waiver that names one
        # end of a two-object violation is not an exact waiver.
        "objects": [(i.get("description") or "")[:160] for i in items],
        "uuids": [i.get("uuid") for i in items if i.get("uuid")],
        "excluded": bool(item.get("excluded", False)),
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
