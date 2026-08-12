"""Placement angles: normalisation, and the reviewed library-zero registry.

Two different things happen to a rotation on its way from a layout into a
placement file, and keeping them apart is the whole job.

*Normalisation* moves an angle into the range the assembly house reads. It is
arithmetic, it applies to everything, and it changes no part's orientation.

A *library-zero offset* does change orientation. It exists because the part's
zero orientation in the assembly house's library need not match the zero of the
footprint in the layout, and where they differ every instance of that part is
fitted turned by the difference. That is a property of the part, so it is
looked up by distributor part number and never by footprint name: two parts can
share a footprint name and differ in the house's library.

An offset must never be invented to turn a negative angle positive - that is
what normalisation is for, and an offset would turn a part that was right. And
a part with no reviewed entry is not assumed to need no offset: "we have not
looked at this one" and "we looked and it needs nothing" are different
statements, and only the second is safe to ship.
"""

from __future__ import annotations


class OrientationError(Exception):
    """The registry cannot answer for a part that is about to be shipped."""


def normalise(angle, low=0.0, high=360.0):
    """Put an angle in [low, high). Same orientation, said the expected way."""
    return low + (float(angle) - low) % (high - low)


class Registry:
    """The reviewed offsets, indexed by part number.

    Built from the board manifest. Every lookup either returns a reviewed
    entry or raises: there is no default, because a silent zero is exactly the
    failure this exists to prevent.
    """

    REQUIRED_FIELDS = ("lcsc", "mpn", "package", "kicad_footprint",
                       "offset_deg", "review_status", "evidence_file",
                       "evidence_sha256")

    def __init__(self, spec):
        self.spec = spec or {}
        self.part_number_field = self.spec.get("part_number_field", "MPN")
        low, high = self.spec.get("normalize_range_deg", [0, 360])
        self.low, self.high = float(low), float(high)
        self.entries = {}
        self.duplicates = []
        for row in self.spec.get("registry", []):
            lcsc = str(row.get("lcsc", "")).strip()
            if not lcsc:
                continue
            if lcsc in self.entries:
                if float(self.entries[lcsc]["offset_deg"]) != float(
                        row["offset_deg"]):
                    self.duplicates.append(lcsc)
                continue
            self.entries[lcsc] = row

    def defects(self):
        """Ways the registry is unusable as written, before any board is read."""
        problems = []
        for lcsc in sorted(set(self.duplicates)):
            problems.append({
                "lcsc": lcsc,
                "issue": "declared twice with different offsets, so which one "
                         "applies depends on read order"})
        for lcsc, row in sorted(self.entries.items()):
            for field in self.REQUIRED_FIELDS:
                if str(row.get(field, "")).strip() == "":
                    problems.append({
                        "lcsc": lcsc,
                        "issue": "the entry records no {}; a reviewed offset "
                                 "nobody can re-check is not reviewed".format(
                                     field)})
            try:
                float(row.get("offset_deg"))
            except (TypeError, ValueError):
                problems.append({"lcsc": lcsc,
                                 "issue": "the offset is not a number",
                                 "value": row.get("offset_deg")})
        return problems

    def offset(self, lcsc):
        """The reviewed offset for a part. Raises if there is not one."""
        if not lcsc:
            raise OrientationError(
                "a placement carries no part number, so no reviewed "
                "orientation can be found for it")
        row = self.entries.get(lcsc)
        if row is None:
            raise OrientationError(
                "{} has no reviewed orientation entry; a part whose library "
                "zero nobody has checked must not be assumed to need no "
                "correction".format(lcsc))
        return float(row["offset_deg"])

    def angle_for(self, lcsc, board_angle):
        """The placement angle to ship: board angle, offset applied, normalised."""
        return normalise(float(board_angle) + self.offset(lcsc),
                         self.low, self.high)

    def covers(self, lcsc):
        return lcsc in self.entries


def apply_to_rows(rows, registry, part_numbers, designator_field,
                  rotation_field, decimals=4):
    """Rewrite each row's angle in place. Returns (applied, problems).

    Every row must resolve to a reviewed entry. A row that cannot is left
    untouched and reported: shipping it with an unreviewed angle is the
    outcome this refuses to produce.
    """
    applied, problems = {}, []
    for row in rows:
        reference = str(row.get(designator_field, "")).strip()
        raw = row.get(rotation_field, "")
        try:
            board_angle = float(raw)
        except (TypeError, ValueError):
            problems.append({"reference": reference,
                             "issue": "rotation is not a number",
                             "value": raw})
            continue
        lcsc = part_numbers.get(reference)
        try:
            final = registry.angle_for(lcsc, board_angle)
        except OrientationError as exc:
            problems.append({"reference": reference, "lcsc": lcsc or None,
                             "issue": str(exc)})
            continue
        row[rotation_field] = "{:.{}f}".format(final, decimals)
        applied[reference] = {
            "lcsc": lcsc,
            "board_deg": board_angle,
            "offset_deg": registry.offset(lcsc),
            "shipped_deg": final,
        }
    return applied, problems
