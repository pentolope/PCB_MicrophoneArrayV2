"""KiCad ERC/DRC report readers, validated against the official schemas.

KiCad 10 does not use one shape for both reports:

  DRC  top-level `violations`, `unconnected_items`, `schematic_parity`
  ERC  no top-level `violations` at all - findings live under
       `sheets[].violations`, one entry per sheet

Reading `doc["violations"]` for ERC therefore always yields an empty list and
the gate passes no matter what the schematic contains. That was a real
false-PASS in an earlier implementation, and it is the reason nothing here is
inferred from the shape of the document in front of it. Every report is checked
against the vendored copy of the schema it declares (see
`schemas/kicad10/PROVENANCE.md`) before a single field is read.

Two things this module is careful about:

**Coordinates are not millimetres until they are converted.** Both schemas
permit `mm`, `mils` and `in`, and ERC does not even require the units field to
be present. Every position is converted to millimetres here and stored only in
millimetres, so nothing downstream - a clearance comparison, a waiver location,
a report line - can be reading inches under a name that says mm.

**A malformed report is an error, not an empty one.** Validation happens before
anything is normalised and long before waivers are considered, so a report that
cannot be trusted can never be quietly waived into a pass.
"""

from __future__ import annotations

from . import schema as _schema
from .schema import ValidationError, loads, load_report      # noqa: F401


class ReportSchemaError(Exception):
    pass


# Schema markers this reader implements, and the vendored file each maps to.
SUPPORTED_SCHEMAS = {
    "ERC": {"https://schemas.kicad.org/erc.v1.json": "erc"},
    "DRC": {"https://schemas.kicad.org/drc.v1.json": "drc"},
}

# Major versions whose report structure has been verified against the real
# tool. A newer major may move findings again, exactly as KiCad 10 did.
SUPPORTED_KICAD_MAJOR = (10,)

# Units the schemas permit, and what one of each is in millimetres.
UNITS_TO_MM = {"mm": 1.0, "in": 25.4, "mils": 0.0254}

# Fields this framework adds to a report it generated, for its own provenance.
# They are stripped before schema validation, because the schemas declare
# `additionalProperties: false` and would otherwise reject our own annotations
# as if KiCad had written them.
VALIDATOR_ANNOTATIONS = ("source_sha256", "source_closure_sha256",
                         "source_closure")

# Required by this validator, though optional in the schema: a report that does
# not say which severities it included cannot be evidence that anything was
# checked, and one that hides its ignored checks cannot be evidence that
# everything was.
REQUIRED_BEYOND_SCHEMA = ("included_severities", "ignored_checks")

DRC_BUCKETS = ("violations", "unconnected_items", "schematic_parity")


def _validate(doc, kind):
    """Schema-validate and return (document, units, mm_per_unit)."""
    if not isinstance(doc, dict):
        raise ReportSchemaError(
            f"{kind} report is a {type(doc).__name__}, not a JSON object")

    marker = doc.get("$schema")
    known = SUPPORTED_SCHEMAS[kind]
    if marker not in known:
        raise ReportSchemaError(
            f"{kind} report declares schema {marker!r}; this validator "
            f"implements {sorted(known)} and refuses to read a layout it has "
            f"not verified")

    try:
        vendored = _schema.load_schema(known[marker])
    except _schema.SchemaError as exc:
        raise ReportSchemaError(
            f"the vendored {kind} schema is unusable: {exc}") from exc

    subject = {k: v for k, v in doc.items() if k not in VALIDATOR_ANNOTATIONS}
    try:
        _schema.validate(subject, vendored)
    except ValidationError as exc:
        raise ReportSchemaError(
            f"{kind} report does not satisfy {marker}: {exc}") from exc

    version = str(doc.get("kicad_version") or "")
    major = version.split(".")[0]
    if not major.isdigit() or int(major) not in SUPPORTED_KICAD_MAJOR:
        raise ReportSchemaError(
            f"{kind} report was produced by KiCad {version!r}; report structure "
            f"is version-specific and only major version(s) "
            f"{list(SUPPORTED_KICAD_MAJOR)} have been verified")

    missing = [k for k in REQUIRED_BEYOND_SCHEMA if k not in doc]
    if missing:
        raise ReportSchemaError(
            f"{kind} report omits {missing}. The published schema makes these "
            f"optional; this validator does not, because a report that does "
            f"not state which severities it included is not evidence that "
            f"anything was checked")

    units = doc.get("coordinate_units")
    if units is None:
        raise ReportSchemaError(
            f"{kind} report does not state its coordinate units, so no "
            f"position in it can be placed on the board")
    if units not in UNITS_TO_MM:
        raise ReportSchemaError(
            f"{kind} report declares coordinate units {units!r}; supported "
            f"units are {sorted(UNITS_TO_MM)}")
    return doc, units, UNITS_TO_MM[units]


def parse_drc(doc):
    doc, units, scale = _validate(doc, "DRC")
    findings = []
    for bucket in DRC_BUCKETS:
        for item in doc[bucket]:
            findings.append(_normalise(item, bucket, scale, units))
    return findings, _meta(doc)


def parse_erc(doc):
    if isinstance(doc, dict) and "violations" in doc:
        # Caught before schema validation only so the message names the actual
        # mistake rather than "additionalProperties".
        raise ReportSchemaError(
            "ERC report has an unexpected top-level `violations`; the schema "
            "this validator implements puts them under sheets[].violations")
    doc, units, scale = _validate(doc, "ERC")
    if not doc["sheets"]:
        raise ReportSchemaError(
            "ERC report lists no sheets at all; an empty sheet list is not the "
            "same as a schematic with no problems")
    findings = []
    for sheet in doc["sheets"]:
        for item in sheet["violations"]:
            entry = _normalise(item, "violations", scale, units)
            entry["sheet"] = sheet.get("path") or sheet.get("uuid_path")
            findings.append(entry)
    return findings, _meta(doc)


def _normalise(item, bucket, scale, units):
    """One finding, with its position converted to millimetres."""
    items = item["items"]
    first = items[0] if items else {}
    pos = first.get("pos") or {}
    x = pos.get("x")
    y = pos.get("y")
    return {
        "category": bucket,
        "severity": item["severity"],
        "rule": item["type"],
        "description": (item.get("description") or "")[:200],
        "object": (first.get("description") or "")[:160],
        # Every affected object, not just the first: a waiver that names one
        # end of a two-object violation is not an exact waiver.
        "objects": [(i.get("description") or "")[:160] for i in items],
        "uuids": [i["uuid"] for i in items if i.get("uuid")],
        "excluded": bool(item.get("excluded", False)),
        # Canonical millimetres, always. The units the report used are kept
        # only so a result can be traced back to what was read.
        "x_mm": None if x is None else x * scale,
        "y_mm": None if y is None else y * scale,
        "source_units": units,
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
