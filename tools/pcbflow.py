#!/usr/bin/env python3
"""Fail-closed KiCad/FreeRouting/JLCPCB workflow gates.

This script supplies cross-artifact and orchestration checks. It does not replace
KiCad DRC, project-specific signal-integrity analysis, or human visual review.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
BRIDGE = SCRIPT_DIR / "kicad_specctra.py"
SVG_CONVERTER = SCRIPT_DIR / "svg_to_png.cjs"
PLACEHOLDER_WORDS = ("replace-me", "replace_with", "2.2.x")


class GateError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def quote_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline([str(value) for value in command])


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    print("+", quote_command(command))
    result = subprocess.run(
        [str(value) for value in command],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        env=env,
        check=False,
    )
    if capture and result.stdout:
        print(result.stdout.rstrip())
    if check and result.returncode:
        raise GateError(
            f"Command failed with exit code {result.returncode}: "
            f"{quote_command(command)}"
        )
    return result


def load_config(config_path: Path) -> tuple[dict[str, Any], Path]:
    config_path = config_path.resolve()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"Cannot read valid JSON config {config_path}: {exc}") from exc
    return config, config_path.parent


def resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def copy_project_context(
    config: dict[str, Any], base: Path, destination: Path
) -> Path:
    source_board = resolve(base, config["project"]["board"])
    source_root = source_board.parent

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {
            name
            for name in names
            if name in {".git", "generated", "__pycache__", ".pytest_cache"}
            or name.endswith((".zip", ".7z", ".rar"))
        }
        return ignored

    shutil.copytree(source_root, destination, ignore=ignore)
    copied_board = destination / source_board.name
    if not copied_board.is_file():
        raise GateError("Project-context copy omitted the board.")

    configured_project = resolve(base, config["project"]["project_file"])
    copied_project = destination / configured_project.name
    if not copied_project.is_file():
        shutil.copy2(configured_project, copied_project)
    return copied_board


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(f"{name} must be a JSON object.")
    return value


def check_config_data(config: dict[str, Any], base: Path) -> list[str]:
    errors: list[str] = []
    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for section in ("project", "toolchain", "board", "routing", "release", "checks"):
        if not isinstance(config.get(section), dict):
            errors.append(f"missing object: {section}")
    if errors:
        return errors

    project = config["project"]
    for key in ("name", "board", "project_file"):
        if not project.get(key):
            errors.append(f"project.{key} is required")
    for key in ("board", "project_file"):
        value = str(project.get(key, ""))
        if value and not resolve(base, value).is_file():
            errors.append(f"project.{key} does not exist: {value}")
    if project.get("board") and project.get("project_file"):
        if Path(str(project["board"])).stem != Path(str(project["project_file"])).stem:
            errors.append(
                "project.board and project.project_file must share a filename stem"
            )
    schematic = str(project.get("schematic", "")).strip()
    if schematic and not resolve(base, schematic).is_file():
        errors.append(f"project.schematic does not exist: {schematic}")

    serialized = json.dumps(config).lower()
    for placeholder in PLACEHOLDER_WORDS:
        if placeholder in serialized:
            errors.append(f"unresolved template placeholder: {placeholder}")

    board = config["board"]
    layers = board.get("copper_layers")
    routable = board.get("routable_layers")
    if not isinstance(layers, list) or len(layers) < 2:
        errors.append("board.copper_layers must list at least two layers")
    if not isinstance(routable, list) or len(routable) != len(layers or []):
        errors.append(
            "board.routable_layers must match board.copper_layers in length"
        )
    allowed = board.get("allowed_track_layers")
    if not isinstance(allowed, list) or not set(allowed).issubset(set(layers or [])):
        errors.append("board.allowed_track_layers must be a copper-layer subset")

    route = config["routing"]
    if len(route.get("preferred_direction_horizontal", [])) != len(layers or []):
        errors.append(
            "routing.preferred_direction_horizontal must match copper layer count"
        )
    ignored = set(route.get("ignore_net_classes", []))
    required_ignored = set(board.get("plane_net_classes", [])) | set(
        board.get("critical_net_classes", [])
    )
    missing = sorted(required_ignored - ignored)
    if missing:
        errors.append(
            "routing.ignore_net_classes is missing plane/critical classes: "
            + ", ".join(missing)
        )
    if not route.get("seeds"):
        errors.append("routing.seeds must contain at least one recorded seed")

    tool_hash = str(config["toolchain"].get("freerouting_sha256", ""))
    if not re.fullmatch(r"[0-9a-fA-F]{64}", tool_hash):
        errors.append("toolchain.freerouting_sha256 must be 64 hexadecimal digits")

    custom_entries = config.get("checks", {}).get("custom_commands", [])
    custom_ids = {
        entry.get("id")
        for entry in custom_entries
        if isinstance(entry, dict) and entry.get("id")
    }
    missing_custom = sorted(
        set(config.get("checks", {}).get("required_custom_ids", [])) - custom_ids
    )
    if missing_custom:
        errors.append(
            "missing required custom check IDs: " + ", ".join(missing_custom)
        )
    for entry in custom_entries:
        if not isinstance(entry, dict):
            continue
        command = entry.get("command", [])
        if (
            isinstance(command, list)
            and len(command) >= 2
            and str(command[1]).endswith(".py")
            and "{" not in str(command[1])
            and not resolve(base, str(command[1])).is_file()
        ):
            errors.append(
                f"custom check script does not exist: {entry.get('id', command[1])}"
            )

    covering = board.get("via_covering", {})
    if covering.get("process") == "plugged":
        if float(covering.get("min_mask_opening_clearance_mm", 0)) < 0.35:
            errors.append(
                "plugged-via mask-opening clearance cannot be below 0.35 mm"
            )
        if float(covering.get("max_via_diameter_mm", 99)) > 0.5:
            errors.append("ordinary plugged-via diameter cannot exceed 0.50 mm")
        if not covering.get("require_closed_both_sides"):
            errors.append("ordinary plugged vias must be closed in both masks")
    return errors


def command_check_config(args: argparse.Namespace) -> None:
    config, base = load_config(Path(args.config))
    errors = check_config_data(config, base)
    if errors:
        raise GateError("Config gate failed:\n- " + "\n- ".join(errors))
    print("Config gate passed.")


def extract_blocks(text: str, symbol: str) -> list[str]:
    """Extract balanced S-expression blocks beginning with SYMBOL."""

    result: list[str] = []
    pattern = re.compile(r"\(" + re.escape(symbol) + r"(?=[\s)])")
    for match in pattern.finditer(text):
        start = match.start()
        if start and text[start - 1] not in " \t\r\n(":
            continue
        depth = 0
        quoted = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    result.append(text[start : index + 1])
                    break
    return result


def parse_pair(block: str, key: str) -> tuple[float, float] | None:
    match = re.search(
        rf"\({re.escape(key)}\s+([-+]?\d+(?:\.\d+)?)\s+"
        rf"([-+]?\d+(?:\.\d+)?)",
        block,
    )
    return (float(match.group(1)), float(match.group(2))) if match else None


def parse_number(block: str, key: str) -> float | None:
    match = re.search(
        rf"\({re.escape(key)}\s+([-+]?\d+(?:\.\d+)?)", block
    )
    return float(match.group(1)) if match else None


def parse_string(block: str, key: str) -> str | None:
    match = re.search(rf"\({re.escape(key)}\s+\"([^\"]+)\"", block)
    return match.group(1) if match else None


def parse_int(block: str, key: str) -> int | None:
    match = re.search(rf"\({re.escape(key)}\s+(-?\d+)", block)
    return int(match.group(1)) if match else None


def rounded(point: tuple[float, float], digits: int = 6) -> tuple[float, float]:
    return (round(point[0], digits), round(point[1], digits))


@dataclass(frozen=True)
class Segment:
    start: tuple[float, float]
    end: tuple[float, float]
    width: float
    layer: str
    net: int

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)


@dataclass(frozen=True)
class Via:
    at: tuple[float, float]
    size: float
    drill: float
    net: int


def board_entities(board_path: Path) -> dict[str, Any]:
    text = board_path.read_text(encoding="utf-8")
    layer_blocks = extract_blocks(text, "layers")
    layers: list[str] = []
    if layer_blocks:
        for match in re.finditer(
            r"\(\s*\d+\s+\"([^\"]+\.Cu)\"\s+(?:signal|power|mixed|jumper)",
            layer_blocks[0],
        ):
            layers.append(match.group(1))
    nets = {
        int(number): name
        for number, name in re.findall(r'\(net\s+(\d+)\s+"([^"]*)"\)', text)
    }

    segments: list[Segment] = []
    for block in extract_blocks(text, "segment"):
        start = parse_pair(block, "start")
        end = parse_pair(block, "end")
        width = parse_number(block, "width")
        layer = parse_string(block, "layer")
        net = parse_int(block, "net")
        if None not in (start, end, width, layer, net):
            segments.append(
                Segment(
                    start=start,  # type: ignore[arg-type]
                    end=end,  # type: ignore[arg-type]
                    width=float(width),
                    layer=str(layer),
                    net=int(net),
                )
            )

    vias: list[Via] = []
    for block in extract_blocks(text, "via"):
        at = parse_pair(block, "at")
        size = parse_number(block, "size")
        drill = parse_number(block, "drill")
        net = parse_int(block, "net")
        if None not in (at, size, drill, net):
            vias.append(
                Via(
                    at=at,  # type: ignore[arg-type]
                    size=float(size),
                    drill=float(drill),
                    net=int(net),
                )
            )
    return {
        "text": text,
        "layers": layers,
        "nets": nets,
        "segments": segments,
        "vias": vias,
        "arc_count": len(extract_blocks(text, "arc")),
    }


def turn_degrees(
    vector_a: tuple[float, float], vector_b: tuple[float, float]
) -> float:
    norm_a = math.hypot(*vector_a)
    norm_b = math.hypot(*vector_b)
    if norm_a == 0 or norm_b == 0:
        return 180.0
    cosine = max(
        -1.0,
        min(
            1.0,
            (vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1])
            / (norm_a * norm_b),
        ),
    )
    included = math.degrees(math.acos(cosine))
    return 180.0 - included


def route_corner_findings(
    segments: list[Segment], max_turn: float, tolerance: float
) -> list[dict[str, Any]]:
    endpoints: dict[
        tuple[int, str, tuple[float, float]], list[tuple[float, float]]
    ] = defaultdict(list)
    for segment in segments:
        start = rounded(segment.start)
        end = rounded(segment.end)
        endpoints[(segment.net, segment.layer, start)].append(
            (segment.end[0] - segment.start[0], segment.end[1] - segment.start[1])
        )
        endpoints[(segment.net, segment.layer, end)].append(
            (segment.start[0] - segment.end[0], segment.start[1] - segment.end[1])
        )

    findings = []
    for (net, layer, at), vectors in sorted(endpoints.items()):
        if len(vectors) != 2:
            continue
        turn = turn_degrees(vectors[0], vectors[1])
        if turn > max_turn + tolerance:
            findings.append(
                {
                    "net": net,
                    "layer": layer,
                    "at_mm": list(at),
                    "turn_degrees": round(turn, 3),
                }
            )
    return findings


def point_segment_distance(
    point_value: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.dist(point_value, start)
    ratio = (
        (point_value[0] - start[0]) * dx + (point_value[1] - start[1]) * dy
    ) / length_squared
    ratio = max(0.0, min(1.0, ratio))
    closest = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.dist(point_value, closest)


def source_audit(config: dict[str, Any], base: Path, board_path: Path) -> dict[str, Any]:
    entities = board_entities(board_path)
    board = config["board"]
    routing = config["routing"]
    failures: list[str] = []

    expected_layers = list(board["copper_layers"])
    actual_layers = entities["layers"]
    if actual_layers != expected_layers:
        failures.append(
            f"copper layer order differs: expected {expected_layers}, got "
            f"{actual_layers}"
        )

    allowed_layers = set(board["allowed_track_layers"])
    forbidden = sorted(
        {
            segment.layer
            for segment in entities["segments"]
            if segment.layer not in allowed_layers
        }
    )
    if forbidden:
        failures.append("tracks appear on forbidden layers: " + ", ".join(forbidden))

    minimum_width = float(board["absolute_min_track_width_mm"])
    thin = [
        segment
        for segment in entities["segments"]
        if segment.width + 1e-9 < minimum_width
    ]
    if thin:
        examples = ", ".join(
            f"net {segment.net} {segment.width:.4f}mm"
            for segment in thin[:8]
        )
        failures.append(
            f"{len(thin)} tracks are below {minimum_width:.4f} mm ({examples})"
        )

    via_rule = board["via"]
    expected_size = float(via_rule["diameter_mm"])
    expected_drill = float(via_rule["drill_mm"])
    wrong_vias = [
        via
        for via in entities["vias"]
        if not math.isclose(via.size, expected_size, abs_tol=1e-6)
        or not math.isclose(via.drill, expected_drill, abs_tol=1e-6)
    ]
    if wrong_vias:
        examples = ", ".join(
            f"{via.size:.3f}/{via.drill:.3f}@{via.at}" for via in wrong_vias[:8]
        )
        failures.append(
            f"{len(wrong_vias)} vias differ from {expected_size:.3f}/"
            f"{expected_drill:.3f} mm ({examples})"
        )

    minimum_hole_to_hole = float(via_rule["min_hole_to_hole_mm"])
    hole_pair_clearances = []
    bad_hole_pairs = []
    vias = entities["vias"]
    for index, via_a in enumerate(vias):
        for via_b in vias[index + 1 :]:
            clearance = (
                math.dist(via_a.at, via_b.at)
                - via_a.drill / 2.0
                - via_b.drill / 2.0
            )
            hole_pair_clearances.append(clearance)
            if clearance + 1e-9 < minimum_hole_to_hole:
                bad_hole_pairs.append((via_a, via_b, clearance))
    if bad_hole_pairs:
        examples = ", ".join(
            f"{clearance:.4f}mm at {via_a.at}/{via_b.at}"
            for via_a, via_b, clearance in bad_hole_pairs[:6]
        )
        failures.append(
            f"{len(bad_hole_pairs)} via-hole pairs are below "
            f"{minimum_hole_to_hole:.3f} mm ({examples})"
        )

    minimum_hole_to_track = float(via_rule["min_hole_to_track_mm"])
    hole_track_clearances = []
    bad_hole_tracks = []
    for via in vias:
        for segment in entities["segments"]:
            if via.net == segment.net:
                continue
            clearance = (
                point_segment_distance(via.at, segment.start, segment.end)
                - via.drill / 2.0
                - segment.width / 2.0
            )
            hole_track_clearances.append(clearance)
            if clearance + 1e-9 < minimum_hole_to_track:
                bad_hole_tracks.append((via, segment, clearance))
    if bad_hole_tracks:
        examples = ", ".join(
            f"{clearance:.4f}mm via net {via.net}/track net {segment.net} "
            f"at {via.at}"
            for via, segment, clearance in bad_hole_tracks[:6]
        )
        failures.append(
            f"{len(bad_hole_tracks)} different-net via-hole/track gaps are below "
            f"{minimum_hole_to_track:.3f} mm ({examples})"
        )

    max_turn = float(routing["max_turn_degrees"])
    tolerance = float(routing.get("corner_tolerance_degrees", 1.0))
    corners = route_corner_findings(entities["segments"], max_turn, tolerance)
    waived_locations = {
        tuple(waiver.get("at_mm", []))
        for waiver in config.get("checks", {}).get("waivers", [])
        if waiver.get("kind") == "route_corner"
    }
    unwaived_corners = [
        row for row in corners if tuple(row["at_mm"]) not in waived_locations
    ]
    if unwaived_corners:
        examples = ", ".join(
            f"{row['turn_degrees']:.1f}deg net {row['net']} "
            f"at {tuple(row['at_mm'])}"
            for row in unwaived_corners[:8]
        )
        failures.append(
            f"{len(unwaived_corners)} route turns exceed {max_turn:.1f} degrees "
            f"({examples})"
        )

    covering = board.get("via_covering", {})
    if covering.get("process") == "plugged":
        max_diameter = float(covering["max_via_diameter_mm"])
        oversized = [via for via in entities["vias"] if via.size > max_diameter + 1e-9]
        if oversized:
            failures.append(
                f"{len(oversized)} vias exceed ordinary plugging diameter "
                f"{max_diameter:.3f} mm"
            )
        text = entities["text"]
        global_tenting = bool(
            re.search(r"\(tenting\s+front\s+back\)", text)
            or re.search(r"\(tenting\s+back\s+front\)", text)
        )
        if covering.get("require_closed_both_sides") and not global_tenting:
            failures.append(
                "source does not request global front-and-back via tenting; "
                "Gerber mask closure must be proved by a project-specific check"
            )

    report = {
        "schema": 1,
        "board": str(board_path.resolve()),
        "copper_layers": actual_layers,
        "track_count": len(entities["segments"]),
        "arc_count": entities["arc_count"],
        "via_count": len(entities["vias"]),
        "total_track_length_mm": round(
            sum(segment.length for segment in entities["segments"]), 6
        ),
        "minimum_track_width_mm": min(
            (segment.width for segment in entities["segments"]), default=None
        ),
        "minimum_via_hole_to_hole_mm": min(
            hole_pair_clearances, default=None
        ),
        "minimum_different_net_via_hole_to_track_mm": min(
            hole_track_clearances, default=None
        ),
        "route_corner_findings": corners,
        "failures": failures,
        "passed": not failures,
    }
    report["report_sha256"] = hashlib.sha256(canonical_json(report)).hexdigest()
    return report


def command_source_audit(args: argparse.Namespace) -> None:
    config, base = load_config(Path(args.config))
    errors = check_config_data(config, base)
    if errors:
        raise GateError("Config gate failed:\n- " + "\n- ".join(errors))
    board_path = resolve(base, config["project"]["board"])
    report = source_audit(config, base, board_path)
    if args.output:
        target = resolve(base, args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise GateError("Source audit failed.")


def waiver_matches(waiver: dict[str, Any], finding: dict[str, Any], kind: str) -> bool:
    if waiver.get("kind") != kind:
        return False
    if kind == "ignored_check":
        return waiver.get("key") == finding.get("key") and all(
            waiver.get(required)
            for required in ("reason", "approved_by", "approved_date")
        )
    if kind in ("violation", "schematic_parity"):
        if waiver.get("type") != finding.get("type"):
            return False
        item_uuids = sorted(
            item.get("uuid") for item in finding.get("items", []) if item.get("uuid")
        )
        waiver_uuids = sorted(waiver.get("uuids", []))
        return item_uuids == waiver_uuids and bool(item_uuids) and all(
            waiver.get(required)
            for required in ("reason", "approved_by", "approved_date")
        )
    return False


def inspect_kicad_report(
    report_path: Path,
    *,
    phase: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"Cannot parse KiCad report {report_path}: {exc}") from exc
    waivers = config.get("checks", {}).get("waivers", [])
    allowed_pre_route = set(
        config.get("checks", {}).get("pre_route_allowed_drc_types", [])
    )
    failures: list[str] = []

    for ignored in report.get("ignored_checks", []):
        if not any(
            waiver_matches(waiver, ignored, "ignored_check") for waiver in waivers
        ):
            failures.append(f"unwaived ignored check: {ignored.get('key')}")

    for section, kind in (
        ("violations", "violation"),
        ("schematic_parity", "schematic_parity"),
    ):
        for finding in report.get(section, []):
            if phase == "pre-route" and finding.get("type") in allowed_pre_route:
                continue
            if not any(waiver_matches(waiver, finding, kind) for waiver in waivers):
                failures.append(
                    f"unwaived {section}: {finding.get('type')} - "
                    f"{finding.get('description', '')}"
                )

    unconnected = report.get("unconnected_items", [])
    if unconnected and phase != "pre-route":
        failures.append(f"{len(unconnected)} unconnected items")

    return {
        "report": str(report_path),
        "ignored_check_count": len(report.get("ignored_checks", [])),
        "violation_count": len(report.get("violations", [])),
        "schematic_parity_count": len(report.get("schematic_parity", [])),
        "unconnected_count": len(unconnected),
        "failures": failures,
        "passed": not failures,
    }


def run_custom_checks(
    config: dict[str, Any],
    base: Path,
    *,
    phase: str,
    board_path: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    results = []
    context = {
        "board": str(board_path),
        "project_dir": str(base),
        "output_dir": str(output_dir),
        "phase": phase,
    }
    for entry in config.get("checks", {}).get("custom_commands", []):
        if isinstance(entry, list):
            entry = {"phase": "all", "command": entry}
        if not isinstance(entry, dict):
            raise GateError("custom_commands entries must be arrays or objects")
        entry_phase = entry.get("phase", "all")
        if entry_phase not in ("all", phase):
            continue
        command = [str(value).format(**context) for value in entry.get("command", [])]
        if not command:
            raise GateError("custom command is empty")
        result = run(command, cwd=base, check=False)
        results.append(
            {
                "phase": phase,
                "command": command,
                "returncode": result.returncode,
                "output": (result.stdout or "")[-10000:],
            }
        )
        if result.returncode:
            raise GateError(f"Custom {phase} check failed: {quote_command(command)}")
    return results


def kicad_cli(config: dict[str, Any], base: Path) -> str:
    value = str(config["toolchain"]["kicad_cli"])
    candidate = resolve(base, value)
    return str(candidate) if candidate.exists() else value


def preflight(
    config: dict[str, Any],
    base: Path,
    *,
    phase: str,
    board_path: Path,
    output_dir: Path,
    save_board: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cli = kicad_cli(config, base)
    result: dict[str, Any] = {"schema": 1, "phase": phase}

    schematic_value = str(config["project"].get("schematic", "")).strip()
    if schematic_value:
        schematic = resolve(base, schematic_value)
        erc_report = output_dir / "erc.json"
        erc_command = [
            cli,
            "sch",
            "erc",
            "--output",
            str(erc_report),
            "--format",
            "json",
            "--units",
            "mm",
            "--severity-all",
            "--exit-code-violations",
            str(schematic),
        ]
        erc_run = run(erc_command, cwd=base, check=False)
        erc_result = inspect_kicad_report(
            erc_report, phase="post-route", config=config
        )
        result["erc"] = erc_result
        if erc_run.returncode or not erc_result["passed"]:
            raise GateError("KiCad ERC gate failed.")

    drc_report = output_dir / "drc.json"
    drc_command = [
        cli,
        "pcb",
        "drc",
        "--output",
        str(drc_report),
        "--format",
        "json",
        "--units",
        "mm",
        "--all-track-errors",
        "--severity-all",
        "--severity-exclusions",
        "--refill-zones",
    ]
    if schematic_value:
        drc_command.append("--schematic-parity")
    if save_board:
        drc_command.append("--save-board")
    drc_command.extend(["--exit-code-violations", str(board_path)])
    drc_run = run(drc_command, cwd=base, check=False)
    drc_result = inspect_kicad_report(drc_report, phase=phase, config=config)
    result["drc"] = drc_result
    if not drc_result["passed"]:
        raise GateError("KiCad DRC gate failed:\n- " + "\n- ".join(drc_result["failures"]))
    if phase == "pre-route":
        if drc_run.returncode not in (0, 5):
            raise GateError(f"KiCad DRC exited with code {drc_run.returncode}.")
    elif drc_run.returncode:
        raise GateError(f"KiCad DRC exited with code {drc_run.returncode}.")

    source = source_audit(config, base, board_path)
    (output_dir / "source-audit.json").write_text(
        json.dumps(source, indent=2) + "\n", encoding="utf-8"
    )
    result["source_audit"] = source
    if not source["passed"]:
        raise GateError("Source audit failed.")

    result["custom_checks"] = run_custom_checks(
        config,
        base,
        phase=phase,
        board_path=board_path,
        output_dir=output_dir,
    )
    result["passed"] = True
    (output_dir / "preflight.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def command_preflight(args: argparse.Namespace) -> None:
    config, base = load_config(Path(args.config))
    errors = check_config_data(config, base)
    if errors:
        raise GateError("Config gate failed:\n- " + "\n- ".join(errors))
    board_path = resolve(base, config["project"]["board"])
    output = resolve(
        base,
        args.output
        or f"{config['release']['root']}/preflight-{args.phase}-{utc_stamp()}",
    )
    result = preflight(
        config,
        base,
        phase=args.phase,
        board_path=board_path,
        output_dir=output,
    )
    print(json.dumps(result, indent=2))


def tool_version(command: Sequence[str], cwd: Path) -> dict[str, Any]:
    result = run(command, cwd=cwd, check=False)
    return {
        "command": list(command),
        "returncode": result.returncode,
        "output": (result.stdout or "").strip()[:4000],
    }


def doctor(config: dict[str, Any], base: Path) -> dict[str, Any]:
    toolchain = config["toolchain"]
    cli = kicad_cli(config, base)
    report = {
        "kicad": tool_version([cli, "version"], base),
        "java": tool_version([str(toolchain["java"]), "-version"], base),
        "node": tool_version([str(toolchain["node"]), "--version"], base),
    }
    version_text = report["kicad"]["output"]
    required_major = int(toolchain["required_kicad_major"])
    match = re.search(r"(\d+)\.(\d+)", version_text)
    if not match or int(match.group(1)) != required_major:
        raise GateError(
            f"Required KiCad major {required_major}; version output was "
            f"{version_text!r}"
        )
    jar = resolve(base, str(toolchain["freerouting_jar"]))
    if not jar.is_file():
        raise GateError(f"FreeRouting JAR not found: {jar}")
    expected_hash = str(toolchain["freerouting_sha256"]).lower()
    actual_hash = sha256(jar)
    report["freerouting"] = {
        "path": str(jar),
        "sha256": actual_hash,
        "help": tool_version(
            [str(toolchain["java"]), "-jar", str(jar), "-help"], base
        ),
    }
    if actual_hash != expected_hash:
        raise GateError(
            f"FreeRouting SHA-256 mismatch: expected {expected_hash}, "
            f"got {actual_hash}"
        )
    help_text = report["freerouting"]["help"]["output"]
    for required in ("-de", "-do", "-drc"):
        if required not in help_text:
            raise GateError(f"FreeRouting help does not advertise {required}.")
    report["passed"] = True
    return report


def command_doctor(args: argparse.Namespace) -> None:
    config, base = load_config(Path(args.config))
    errors = check_config_data(config, base)
    if errors:
        raise GateError("Config gate failed:\n- " + "\n- ".join(errors))
    print(json.dumps(doctor(config, base), indent=2))


def audit_dsn(dsn: Path, config: dict[str, Any]) -> dict[str, Any]:
    text = dsn.read_text(encoding="utf-8", errors="replace")
    failures = []
    for layer in config["board"]["copper_layers"]:
        if f'"{layer}"' not in text and layer not in text:
            failures.append(f"missing layer {layer}")
    if not re.search(r"\(snap_angle\s+fortyfive_degree\)", text):
        failures.append("DSN snap_angle is not fortyfive_degree")
    if "(network" not in text or "(wiring" not in text:
        failures.append("DSN lacks network or wiring section")
    report = {
        "path": str(dsn),
        "sha256": sha256(dsn),
        "size_bytes": dsn.stat().st_size,
        "failures": failures,
        "passed": not failures,
    }
    if failures:
        raise GateError("DSN audit failed:\n- " + "\n- ".join(failures))
    return report


def bridge_command(config: dict[str, Any], base: Path, *args: str) -> list[str]:
    python = str(config["toolchain"]["kicad_python"])
    candidate = resolve(base, python)
    executable = str(candidate) if candidate.exists() else python
    return [executable, str(BRIDGE), *args]


def command_route(args: argparse.Namespace) -> None:
    config, base = load_config(Path(args.config))
    errors = check_config_data(config, base)
    if errors:
        raise GateError("Config gate failed:\n- " + "\n- ".join(errors))
    tools = doctor(config, base)
    source_board = resolve(base, config["project"]["board"])
    route_root = resolve(
        base, args.output or f"{config['release']['root']}/routing-{utc_stamp()}"
    )
    route_root.mkdir(parents=True, exist_ok=False)
    input_project = route_root / "input-project"
    board = copy_project_context(config, base, input_project)
    preflight(
        config,
        base,
        phase="pre-route",
        board_path=board,
        output_dir=route_root / "preflight",
    )
    dsn = route_root / "input.dsn"
    run(bridge_command(config, base, "export", str(board), str(dsn)), cwd=base)
    dsn_report = audit_dsn(dsn, config)
    (route_root / "dsn-audit.json").write_text(
        json.dumps(dsn_report, indent=2) + "\n", encoding="utf-8"
    )

    toolchain = config["toolchain"]
    routing = config["routing"]
    jar = resolve(base, toolchain["freerouting_jar"])
    routable = ",".join(
        "true" if value else "false" for value in config["board"]["routable_layers"]
    )
    directions = ",".join(
        "true" if value else "false"
        for value in routing["preferred_direction_horizontal"]
    )
    ignored = ",".join(routing.get("ignore_net_classes", []))
    candidates = []
    failures = []

    for seed in routing["seeds"]:
        candidate_dir = route_root / f"candidate-{seed}"
        candidate_dir.mkdir()
        candidate_project = candidate_dir / "project"
        shutil.copytree(input_project, candidate_project)
        ses = candidate_dir / "route.ses"
        fr_drc = candidate_dir / "freerouting-drc.json"
        fr_log = candidate_dir / "freerouting.log"
        command = [
            str(toolchain["java"]),
            "-jar",
            str(jar),
            "--gui.enabled=false",
            "-da",
            "-de",
            str(dsn),
            "-do",
            str(ses),
            "-drc",
            str(fr_drc),
            "-mp",
            str(routing["max_passes"]),
            "-mt",
            str(routing["threads"]),
            "-random_seed",
            str(seed),
            f"--router.layers.routable={routable}",
            f"--router.layers.preferred_direction_horizontal={directions}",
            f"--user_data_path={candidate_dir / 'freerouting-data'}",
        ]
        if ignored:
            command.extend(["-inc", ignored])
        result = run(command, cwd=base, check=False)
        fr_log.write_text(result.stdout or "", encoding="utf-8")
        if result.returncode or not ses.is_file():
            failures.append({"seed": seed, "reason": "FreeRouting failed"})
            continue
        routed = candidate_dir / "routed.kicad_pcb"
        try:
            run(
                bridge_command(
                    config, base, "import", str(board), str(ses), str(routed)
                ),
                cwd=base,
            )
            run(
                bridge_command(
                    config,
                    base,
                    "compare",
                    str(board),
                    str(routed),
                    "--output",
                    str(candidate_dir / "invariants.json"),
                ),
                cwd=base,
            )
            routed_in_project = candidate_project / source_board.name
            if routed != routed_in_project:
                os.replace(routed, routed_in_project)
                routed = routed_in_project
            gate = preflight(
                config,
                base,
                phase="post-route",
                board_path=routed,
                output_dir=candidate_dir / "post-route",
                save_board=True,
            )
            audit = gate["source_audit"]
            candidates.append(
                {
                    "seed": seed,
                    "board": str(routed),
                    "via_count": audit["via_count"],
                    "total_track_length_mm": audit["total_track_length_mm"],
                }
            )
        except GateError as exc:
            failures.append({"seed": seed, "reason": str(exc)})

    if not candidates:
        (route_root / "routing-report.json").write_text(
            json.dumps(
                {"passed": False, "candidates": [], "failures": failures}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        raise GateError("No FreeRouting candidate passed all gates.")

    candidates.sort(key=lambda row: (row["via_count"], row["total_track_length_mm"]))
    selected = candidates[0]
    selected_candidate_project = Path(selected["board"]).parent
    selected_project = route_root / "selected-project"
    shutil.copytree(selected_candidate_project, selected_project)
    selected_path = selected_project / source_board.name
    report = {
        "schema": 1,
        "passed": True,
        "toolchain": tools,
        "dsn": dsn_report,
        "candidates": candidates,
        "failures": failures,
        "selected": {**selected, "board": str(selected_path)},
        "source_board_unchanged": True,
    }
    (route_root / "routing-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print("Selected route is a candidate copy; the source board was not overwritten.")


def gerber_file_function(path: Path) -> str | None:
    with path.open("r", encoding="ascii", errors="ignore") as handle:
        for _ in range(200):
            line = handle.readline()
            if not line:
                break
            match = re.search(r"%TF\.FileFunction,([^*%]+)\*%", line)
            if match:
                return match.group(1)
    return None


def has_gerber_payload(path: Path) -> bool:
    text = path.read_text(encoding="ascii", errors="ignore")
    return bool(
        re.search(r"(?:^|\n)X[-+]?\d+(?:Y[-+]?\d+)?D0[13]\*", text)
        or "G36*" in text
    )


def drill_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="ascii", errors="ignore")
    tools = {
        tool: float(diameter)
        for tool, diameter in re.findall(r"^T(\d+)C(\d+(?:\.\d+)?)", text, re.M)
    }
    hits = defaultdict(int)
    current: str | None = None
    for line in text.splitlines():
        tool_match = re.fullmatch(r"T(\d+)", line.strip())
        if tool_match:
            current = tool_match.group(1)
        elif current and re.match(
            r"^X[-+]?\d+(?:\.\d+)?Y[-+]?\d+(?:\.\d+)?", line.strip()
        ):
            hits[current] += 1
    return {
        "file": path.name,
        "tools_mm": tools,
        "hits_by_tool": dict(hits),
        "total_hits": sum(hits.values()),
        "has_header": "M48" in text,
        "has_eof": "M30" in text,
    }


def audit_fabrication(
    fabrication: Path, config: dict[str, Any]
) -> dict[str, Any]:
    files = sorted(path for path in fabrication.iterdir() if path.is_file())
    roles: dict[str, list[str]] = defaultdict(list)
    failures = []
    gerbers = []
    drills = []
    for path in files:
        role = gerber_file_function(path)
        if role:
            gerbers.append(path)
            roles[role].append(path.name)
            text = path.read_text(encoding="ascii", errors="ignore")
            if "M02*" not in text:
                failures.append(f"{path.name} lacks Gerber EOF")
            if role.startswith("Copper,") and not has_gerber_payload(path):
                failures.append(f"{path.name} copper layer has no payload")
        elif path.suffix.lower() in (".drl", ".xln"):
            drills.append(path)

    copper_roles = sorted(role for role in roles if role.startswith("Copper,"))
    expected_layers = config["board"]["copper_layers"]
    if len(copper_roles) != len(expected_layers):
        failures.append(
            f"expected {len(expected_layers)} copper roles, got {len(copper_roles)}"
        )
    for role, names in roles.items():
        if len(names) != 1:
            failures.append(f"duplicate X2 role {role}: {names}")
    for required in ("Soldermask,Top", "Soldermask,Bot", "Profile,NP"):
        if required not in roles:
            failures.append(f"missing X2 role {required}")
    if not drills:
        failures.append("no Excellon drill file found")
    drill_reports = [drill_summary(path) for path in drills]
    for report in drill_reports:
        if not report["has_header"] or not report["has_eof"]:
            failures.append(f"invalid Excellon framing: {report['file']}")

    return {
        "files": [path.name for path in files],
        "x2_roles": dict(sorted(roles.items())),
        "copper_roles": copper_roles,
        "drills": drill_reports,
        "failures": failures,
        "passed": not failures,
    }


def normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise GateError(f"CSV has no header: {path}")
        return reader.fieldnames, list(reader)


def find_column(fieldnames: list[str], aliases: Iterable[str]) -> str:
    normalized = {normalize_header(name): name for name in fieldnames}
    for alias in aliases:
        if normalize_header(alias) in normalized:
            return normalized[normalize_header(alias)]
    raise GateError(
        f"Missing CSV column; accepted aliases {list(aliases)}, got {fieldnames}"
    )


def native_positions(path: Path) -> dict[str, dict[str, Any]]:
    fields, rows = read_csv(path)
    ref = find_column(fields, ("Ref", "Reference", "Designator"))
    x = find_column(fields, ("PosX", "Mid X", "X"))
    y = find_column(fields, ("PosY", "Mid Y", "Y"))
    rot = find_column(fields, ("Rot", "Rotation"))
    side = find_column(fields, ("Side", "Layer"))
    return {
        row[ref].strip(): {
            "x": float(re.sub(r"[^0-9+.\-eE]", "", row[x])),
            "y": float(re.sub(r"[^0-9+.\-eE]", "", row[y])),
            "rotation": float(re.sub(r"[^0-9+.\-eE]", "", row[rot])) % 360.0,
            "side": row[side].strip().lower(),
        }
        for row in rows
        if row.get(ref, "").strip()
    }


def cpl_positions(path: Path) -> dict[str, dict[str, Any]]:
    fields, rows = read_csv(path)
    ref = find_column(fields, ("Designator", "Ref", "Reference"))
    x = find_column(fields, ("Mid X", "PosX", "X"))
    y = find_column(fields, ("Mid Y", "PosY", "Y"))
    rot = find_column(fields, ("Rotation", "Rot"))
    side = find_column(fields, ("Layer", "Side"))
    return {
        row[ref].strip(): {
            "x": float(re.sub(r"[^0-9+.\-eE]", "", row[x])),
            "y": float(re.sub(r"[^0-9+.\-eE]", "", row[y])),
            "rotation": float(re.sub(r"[^0-9+.\-eE]", "", row[rot])) % 360.0,
            "side": row[side].strip().lower(),
        }
        for row in rows
        if row.get(ref, "").strip()
    }


def angular_error(actual: float, expected: float) -> float:
    return abs((actual - expected + 180.0) % 360.0 - 180.0)


def coordinate_determinant(
    native: dict[str, dict[str, Any]], cpl: dict[str, dict[str, Any]]
) -> float | None:
    refs = sorted(set(native) & set(cpl))
    if len(refs) < 3:
        return None
    origin = refs[0]
    best: tuple[float, float] | None = None
    for index, ref_b in enumerate(refs[1:], start=1):
        for ref_c in refs[index + 1 :]:
            a = native[origin]
            b = native[ref_b]
            c = native[ref_c]
            native_area = (b["x"] - a["x"]) * (c["y"] - a["y"]) - (
                b["y"] - a["y"]
            ) * (c["x"] - a["x"])
            if abs(native_area) < 1e-9:
                continue
            ca = cpl[origin]
            cb = cpl[ref_b]
            cc = cpl[ref_c]
            cpl_area = (cb["x"] - ca["x"]) * (cc["y"] - ca["y"]) - (
                cb["y"] - ca["y"]
            ) * (cc["x"] - ca["x"])
            if best is None or abs(native_area) > abs(best[0]):
                best = (native_area, cpl_area)
    return None if best is None else best[1] / best[0]


def bom_references(path: Path) -> set[str]:
    fields, rows = read_csv(path)
    designators = find_column(
        fields, ("Designator", "Reference", "References", "Ref", "Designators")
    )
    result: set[str] = set()
    for row in rows:
        value = row.get(designators, "")
        result.update(re.findall(r"\b[A-Za-z]+[0-9]+\b", value))
    return result


def audit_assembly(
    native_path: Path, cpl_path: Path, bom_path: Path, config: dict[str, Any]
) -> dict[str, Any]:
    native = native_positions(native_path)
    cpl = cpl_positions(cpl_path)
    bom = bom_references(bom_path)
    assembly = config.get("assembly", {})
    excluded = set(assembly.get("hand_soldered_refs", [])) | set(
        assembly.get("dnp_refs", [])
    )
    expected_refs = set(native) - excluded
    failures = []
    if set(cpl) != expected_refs:
        failures.append(
            "CPL reference mismatch: missing="
            + repr(sorted(expected_refs - set(cpl)))
            + " extra="
            + repr(sorted(set(cpl) - expected_refs))
        )
    if bom != set(cpl):
        failures.append(
            "BOM/CPL reference mismatch: missing_from_bom="
            + repr(sorted(set(cpl) - bom))
            + " extra_in_bom="
            + repr(sorted(bom - set(cpl)))
        )
    offsets = assembly.get("rotation_offsets", {})
    determinant = coordinate_determinant(native, cpl)
    if determinant is not None and determinant <= 0:
        failures.append(
            f"CPL coordinate transform is reflected "
            f"(determinant {determinant:.6f})"
        )
    mismatches = []
    for ref in sorted(expected_refs & set(cpl)):
        expected = native[ref]
        actual = cpl[ref]
        offset = float(offsets.get(ref, 0.0))
        issues = []
        if abs(actual["x"] - expected["x"]) > 0.01:
            issues.append("x")
        if abs(actual["y"] - expected["y"]) > 0.01:
            issues.append("y")
        expected_side = "top" if "top" in expected["side"] else "bottom"
        actual_side = "top" if "top" in actual["side"] else "bottom"
        if actual_side != expected_side:
            issues.append("side")
        if angular_error(actual["rotation"], expected["rotation"] + offset) > 0.1:
            issues.append("rotation")
        if issues:
            mismatches.append({"ref": ref, "issues": issues})
    if mismatches:
        failures.append(f"{len(mismatches)} CPL/native position mismatches")
    return {
        "native_count": len(native),
        "cpl_count": len(cpl),
        "bom_reference_count": len(bom),
        "expected_populated_count": len(expected_refs),
        "coordinate_transform_determinant": determinant,
        "mismatches": mismatches,
        "failures": failures,
        "passed": not failures,
    }


def render_cpl_overlay(cpl_path: Path, output: Path) -> None:
    positions = cpl_positions(cpl_path)
    if not positions:
        raise GateError("Cannot render empty CPL.")
    xs = [row["x"] for row in positions.values()]
    ys = [row["y"] for row in positions.values()]
    margin = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.05 + 2.0
    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin
    width, height = max_x - min_x, max_y - min_y
    scale = 8.0
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width * scale:.3f} {height * scale:.3f}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<g stroke="#202020" fill="none" stroke-width="1.2">',
    ]
    for ref, row in sorted(positions.items()):
        x = (row["x"] - min_x) * scale
        y = (max_y - row["y"]) * scale
        angle = math.radians(row["rotation"])
        length = 8.0
        dx, dy = length * math.cos(angle), -length * math.sin(angle)
        color = "#1f77b4" if "top" in row["side"] else "#d62728"
        elements.append(
            f'<g stroke="{color}"><circle cx="{x:.3f}" cy="{y:.3f}" r="2.2"/>'
            f'<line x1="{x:.3f}" y1="{y:.3f}" x2="{x+dx:.3f}" '
            f'y2="{y+dy:.3f}"/></g>'
        )
        elements.append(
            f'<text x="{x+3:.3f}" y="{y-3:.3f}" font-size="7" '
            f'fill="{color}">{ref}</text>'
        )
    elements.extend(["</g>", "</svg>"])
    output.write_text("\n".join(elements) + "\n", encoding="utf-8")


def rasterize_svgs(
    config: dict[str, Any], base: Path, svg_files: list[Path]
) -> list[Path]:
    node = str(config["toolchain"]["node"])
    output = []
    env = os.environ.copy()
    runtime_modules = env.get("CODEX_PRIMARY_RUNTIME_NODE_MODULES", "")
    if runtime_modules:
        env["NODE_PATH"] = os.pathsep.join(
            value for value in (runtime_modules, env.get("NODE_PATH", "")) if value
        )
    for svg in svg_files:
        png = svg.with_suffix(".png")
        run(
            [node, str(SVG_CONVERTER), str(svg), str(png), "2400"],
            cwd=base,
            env=env,
        )
        output.append(png)
    return output


def file_manifest(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)).replace(os.sep, "/"),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def command_release_candidate(args: argparse.Namespace) -> None:
    config, base = load_config(Path(args.config))
    errors = check_config_data(config, base)
    if errors:
        raise GateError("Config gate failed:\n- " + "\n- ".join(errors))

    candidate = resolve(
        base, args.output or f"{config['release']['root']}/candidate-{utc_stamp()}"
    )
    candidate.mkdir(parents=True, exist_ok=False)
    work = candidate / "work"
    fabrication = candidate / "fabrication"
    assembly_dir = candidate / "assembly"
    renders = candidate / "renders"
    reports = candidate / "reports"
    for directory in (work, fabrication, assembly_dir, renders, reports):
        directory.mkdir()

    source_board = resolve(base, config["project"]["board"])
    final_board = copy_project_context(config, base, work / "project")
    gate = preflight(
        config,
        base,
        phase="release",
        board_path=final_board,
        output_dir=reports / "preflight",
        save_board=True,
    )
    cli = kicad_cli(config, base)
    layers = ",".join(config["release"]["gerber_layers"])
    run(
        [
            cli,
            "pcb",
            "export",
            "gerbers",
            "--output",
            str(fabrication),
            "--layers",
            layers,
            "--subtract-soldermask",
            "--check-zones",
            str(final_board),
        ],
        cwd=base,
    )
    run(
        [
            cli,
            "pcb",
            "export",
            "drill",
            "--output",
            str(fabrication),
            "--format",
            "excellon",
            "--excellon-units",
            "mm",
            "--excellon-zeros-format",
            "decimal",
            "--excellon-oval-format",
            "alternate",
            "--excellon-separate-th",
            "--generate-report",
            "--report-path",
            str(reports / "drill-report.txt"),
            str(final_board),
        ],
        cwd=base,
    )
    native_pos = assembly_dir / "native-position.csv"
    pos_command = [
        cli,
        "pcb",
        "export",
        "pos",
        "--output",
        str(native_pos),
        "--side",
        str(config["release"]["assembly_side"]),
        "--format",
        "csv",
        "--units",
        "mm",
        "--exclude-fp-th",
        "--exclude-dnp",
        "--gerber-board-edge",
        str(final_board),
    ]
    run(pos_command, cwd=base)

    for side in ("top", "bottom"):
        run(
            [
                cli,
                "pcb",
                "render",
                "--output",
                str(renders / f"assembly-{side}.png"),
                "--side",
                side,
                "--width",
                "2400",
                "--height",
                "1800",
                "--quality",
                "high",
                "--background",
                "opaque",
                str(final_board),
            ],
            cwd=base,
        )

    assembly = config.get("assembly", {})
    assembly_report: dict[str, Any] = {"required": False, "passed": True}
    assembly_side = str(config["release"].get("assembly_side", "none"))
    if assembly_side != "none":
        cpl_value = str(assembly.get("cpl", "")).strip()
        bom_value = str(assembly.get("bom", "")).strip()
        if not cpl_value or not bom_value:
            raise GateError("PCBA release requires assembly.cpl and assembly.bom.")
        cpl = resolve(base, cpl_value)
        bom = resolve(base, bom_value)
        if not cpl.is_file() or not bom.is_file():
            raise GateError("Configured BOM or CPL does not exist.")
        copied_cpl = assembly_dir / cpl.name
        copied_bom = assembly_dir / bom.name
        shutil.copy2(cpl, copied_cpl)
        shutil.copy2(bom, copied_bom)
        assembly_report = audit_assembly(
            native_pos, copied_cpl, copied_bom, config
        )
        assembly_report["required"] = True
        if not assembly_report["passed"]:
            raise GateError(
                "Assembly audit failed:\n- "
                + "\n- ".join(assembly_report["failures"])
            )
        overlay = renders / "cpl-orientation-overlay.svg"
        render_cpl_overlay(copied_cpl, overlay)

    fab_report = audit_fabrication(fabrication, config)
    if not fab_report["passed"]:
        raise GateError(
            "Fabrication audit failed:\n- " + "\n- ".join(fab_report["failures"])
        )

    render_input = sorted(fabrication.iterdir())
    tracespace_command = [
        str(value) for value in config["toolchain"]["tracespace"]
    ] + ["--out", str(renders / "tracespace"), *map(str, render_input)]
    (renders / "tracespace").mkdir()
    run(tracespace_command, cwd=base)
    svg_files = sorted((renders / "tracespace").rglob("*.svg"))
    overlay_path = renders / "cpl-orientation-overlay.svg"
    if overlay_path.is_file():
        svg_files.append(overlay_path)
    if not svg_files:
        raise GateError("Tracespace produced no SVG renders.")
    pngs = rasterize_svgs(config, base, svg_files)

    custom_release = gate["custom_checks"]
    tool_report = {
        "kicad": tool_version([cli, "version"], base),
        "tracespace_command": tracespace_command,
        "freerouting_jar_sha256": sha256(
            resolve(base, config["toolchain"]["freerouting_jar"])
        ),
    }
    report = {
        "schema": 1,
        "status": "UNSEALED_VISUAL_REVIEW_REQUIRED",
        "candidate": str(candidate),
        "preflight": gate,
        "fabrication": fab_report,
        "assembly": assembly_report,
        "custom_release_checks": custom_release,
        "tools": tool_report,
        "render_pngs": [
            str(path.relative_to(candidate)).replace(os.sep, "/") for path in pngs
        ]
        + ["renders/assembly-top.png", "renders/assembly-bottom.png"],
    }
    report_path = reports / "release-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    manifest = file_manifest(candidate)
    manifest_path = reports / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest_hash = sha256(manifest_path)
    review = {
        "schema": 1,
        "candidate": str(candidate),
        "candidate_manifest_sha256": manifest_hash,
        "reviewer": "",
        "reviewed_at": "",
        "checks": {
            "outline_cutouts": {"passed": False, "notes": ""},
            "drill_alignment_inventory": {"passed": False, "notes": ""},
            "all_copper_layers": {"passed": False, "notes": ""},
            "mask_and_via_covering": {"passed": False, "notes": ""},
            "paste_and_silkscreen": {"passed": False, "notes": ""},
            "assembly_top": {"passed": False, "notes": ""},
            "assembly_bottom": {"passed": False, "notes": ""},
            "pin1_polarity_ports_connectors": {"passed": False, "notes": ""},
            "dnp_and_hand_soldered_parts": {"passed": False, "notes": ""},
        },
    }
    (candidate / "visual-review.json").write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print(f"Release candidate created at {candidate}")
    print("No production ZIP was created. Inspect every listed render, record the")
    print("visual review, then run the seal command.")


def validate_visual_review(review: dict[str, Any], manifest_hash: str) -> None:
    failures = []
    if review.get("candidate_manifest_sha256") != manifest_hash:
        failures.append("candidate manifest hash does not match")
    if not str(review.get("reviewer", "")).strip():
        failures.append("reviewer is blank")
    if not str(review.get("reviewed_at", "")).strip():
        failures.append("reviewed_at is blank")
    checks = review.get("checks", {})
    if not isinstance(checks, dict) or not checks:
        failures.append("review checks are missing")
    else:
        for name, result in checks.items():
            if not isinstance(result, dict) or result.get("passed") is not True:
                failures.append(f"{name} is not passed")
                continue
            if len(str(result.get("notes", "")).strip()) < 12:
                failures.append(f"{name} notes are not specific enough")
    if failures:
        raise GateError("Visual review gate failed:\n- " + "\n- ".join(failures))


def command_seal(args: argparse.Namespace) -> None:
    config, base = load_config(Path(args.config))
    candidate = resolve(base, args.candidate)
    review_path = resolve(base, args.review)
    if not candidate.is_dir():
        raise GateError(f"Candidate directory does not exist: {candidate}")
    manifest_path = candidate / "reports" / "candidate-manifest.json"
    report_path = candidate / "reports" / "release-report.json"
    if not manifest_path.is_file() or not report_path.is_file():
        raise GateError("Candidate lacks release report or manifest.")
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_manifest = [
        row
        for row in file_manifest(candidate)
        if row["path"]
        not in (
            "visual-review.json",
            str(review_path.relative_to(candidate)).replace(os.sep, "/")
            if review_path.is_relative_to(candidate)
            else "",
            "reports/candidate-manifest.json",
            "reports/release-report.json",
        )
    ]
    saved_comparable = [
        row
        for row in saved_manifest
        if row["path"]
        not in (
            "visual-review.json",
            "reports/candidate-manifest.json",
            "reports/release-report.json",
        )
    ]
    if current_manifest != saved_comparable:
        raise GateError("Candidate files changed after release generation.")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    validate_visual_review(review, sha256(manifest_path))

    sealed = candidate / "sealed"
    sealed.mkdir(exist_ok=False)
    fabrication = candidate / "fabrication"
    zip_path = sealed / f"{config['project']['name']}-JLCPCB-Gerbers.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(fabrication.iterdir()):
            if path.is_file():
                archive.write(path, path.name)
    for path in sorted((candidate / "assembly").iterdir()):
        if path.is_file() and path.name != "native-position.csv":
            shutil.copy2(path, sealed / path.name)
    shutil.copy2(review_path, sealed / "visual-review.json")
    sealed_manifest = file_manifest(sealed)
    (sealed / "SHA256SUMS.json").write_text(
        json.dumps(sealed_manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Sealed release: {sealed}")
    print(f"Fabrication ZIP SHA-256: {sha256(zip_path)}")
    print("This seals local evidence only; it does not approve a JLCPCB order.")


def command_self_test(args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory(prefix="pcbflow-selftest-") as temp_value:
        root = Path(temp_value)
        board_text = """(kicad_pcb
  (version 20250114)
  (layers
    (0 "F.Cu" signal)
    (2 "In1.Cu" power)
    (4 "In2.Cu" power)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user))
  (setup (tenting front back))
  (net 0 "")
  (net 1 "TEST")
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net 1))
  (segment (start 20 10) (end 25 15) (width 0.2) (layer "F.Cu") (net 1))
  (via (at 25 15) (size 0.45) (drill 0.3)
    (layers "F.Cu" "B.Cu") (net 1)))
"""
        board = root / "test.kicad_pcb"
        project = root / "test.kicad_pro"
        board.write_text(board_text, encoding="utf-8")
        project.write_text("{}\n", encoding="utf-8")
        config = {
            "schema_version": 1,
            "project": {
                "name": "selftest",
                "board": board.name,
                "schematic": "",
                "project_file": project.name,
            },
            "toolchain": {
                "kicad_cli": "kicad-cli",
                "kicad_python": "python",
                "required_kicad_major": 10,
                "freerouting_jar": "freerouting-2.2.4.jar",
                "freerouting_sha256": "0" * 64,
                "java": "java",
                "node": "node",
                "tracespace": ["tracespace"],
            },
            "board": {
                "copper_layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
                "routable_layers": [True, False, False, True],
                "allowed_track_layers": ["F.Cu", "B.Cu"],
                "plane_net_classes": ["PLANE"],
                "critical_net_classes": ["MANUAL"],
                "default_track_width_mm": 0.2,
                "absolute_min_track_width_mm": 0.1,
                "default_min_clearance_mm": 0.2,
                "min_copper_to_edge_mm": 0.3,
                "via": {
                    "diameter_mm": 0.45,
                    "drill_mm": 0.3,
                    "min_hole_to_hole_mm": 0.25,
                    "min_hole_to_track_mm": 0.25,
                },
                "via_covering": {
                    "process": "plugged",
                    "max_via_diameter_mm": 0.5,
                    "min_mask_opening_clearance_mm": 0.4,
                    "require_closed_both_sides": True,
                },
            },
            "routing": {
                "max_turn_degrees": 45.0,
                "corner_tolerance_degrees": 1.0,
                "max_passes": 10,
                "threads": 1,
                "seeds": [17],
                "ignore_net_classes": ["PLANE", "MANUAL"],
                "preferred_direction_horizontal": [True, False, True, False],
            },
            "release": {
                "root": "generated/pcbflow",
                "gerber_layers": [],
                "assembly_side": "none",
            },
            "assembly": {
                "rotation_offsets": {"U1": 90.0},
                "hand_soldered_refs": [],
                "dnp_refs": [],
            },
            "checks": {
                "pre_route_allowed_drc_types": ["unconnected_items"],
                "waivers": [],
                "custom_commands": [],
            },
        }
        config_errors = check_config_data(config, root)
        if config_errors:
            raise GateError("Self-test config failed: " + repr(config_errors))
        good = source_audit(config, root, board)
        if not good["passed"]:
            raise GateError("Self-test 45-degree board did not pass.")
        bad_board = root / "bad.kicad_pcb"
        bad_board.write_text(
            board_text.replace("(end 25 15)", "(end 20 20)"),
            encoding="utf-8",
        )
        bad = source_audit(config, root, bad_board)
        if bad["passed"] or not bad["route_corner_findings"]:
            raise GateError("Self-test 90-degree route was not rejected.")

        native = root / "native.csv"
        native.write_text(
            "Ref,Val,Package,PosX,PosY,Rot,Side\n"
            "R1,10k,0402,10,20,0,top\n"
            "U1,IC,QFN,30,40,90,top\n"
            "C1,100n,0402,50,20,45,top\n",
            encoding="utf-8",
        )
        cpl = root / "cpl.csv"
        cpl.write_text(
            "Designator,Mid X,Mid Y,Layer,Rotation\n"
            "R1,10mm,20mm,Top,0\n"
            "U1,30mm,40mm,Top,180\n"
            "C1,50mm,20mm,Top,45\n",
            encoding="utf-8",
        )
        mirrored = root / "mirrored.csv"
        mirrored.write_text(
            cpl.read_text(encoding="utf-8")
            .replace(",20mm,", ",-20mm,")
            .replace(",40mm,", ",-40mm,"),
            encoding="utf-8",
        )
        bom = root / "bom.csv"
        bom.write_text(
            "Comment,Designator\n10k,R1\nIC,U1\n100n,C1\n", encoding="utf-8"
        )
        good_assembly = audit_assembly(native, cpl, bom, config)
        bad_assembly = audit_assembly(native, mirrored, bom, config)
        if not good_assembly["passed"]:
            raise GateError("Self-test valid assembly data did not pass.")
        if (
            bad_assembly["passed"]
            or (bad_assembly["coordinate_transform_determinant"] or 1.0) >= 0
        ):
            raise GateError("Self-test reflected CPL was not rejected.")

        try:
            validate_visual_review(
                {
                    "candidate_manifest_sha256": "wrong",
                    "reviewer": "",
                    "reviewed_at": "",
                    "checks": {},
                },
                "expected",
            )
        except GateError:
            pass
        else:
            raise GateError("Self-test blank visual approval unexpectedly passed.")

        print(
            json.dumps(
                {
                    "passed": True,
                    "checks": [
                        "config",
                        "45-degree route acceptance",
                        "90-degree route rejection",
                        "CPL/BOM/native-position agreement",
                        "reflected coordinate-frame rejection",
                        "blank visual-approval rejection",
                    ],
                },
                indent=2,
            )
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)

    self_test = sub.add_parser(
        "self-test", help="exercise dependency-free workflow gates"
    )
    self_test.set_defaults(func=command_self_test)

    check = sub.add_parser("check-config", help="validate the workflow manifest")
    check.add_argument("config")
    check.set_defaults(func=command_check_config)

    source = sub.add_parser(
        "source-audit", help="audit layers, vias, widths, and route turns"
    )
    source.add_argument("config")
    source.add_argument("--output")
    source.set_defaults(func=command_source_audit)

    preflight_parser = sub.add_parser(
        "preflight", help="run KiCad and custom pre/post-route gates"
    )
    preflight_parser.add_argument("config")
    preflight_parser.add_argument(
        "--phase", choices=("pre-route", "post-route", "release"), required=True
    )
    preflight_parser.add_argument("--output")
    preflight_parser.set_defaults(func=command_preflight)

    doctor_parser = sub.add_parser("doctor", help="verify pinned toolchain")
    doctor_parser.add_argument("config")
    doctor_parser.set_defaults(func=command_doctor)

    route_parser = sub.add_parser(
        "route", help="generate and gate FreeRouting candidates"
    )
    route_parser.add_argument("config")
    route_parser.add_argument("--output")
    route_parser.set_defaults(func=command_route)

    release = sub.add_parser(
        "release-candidate", help="generate an unsealed release and renders"
    )
    release.add_argument("config")
    release.add_argument("--output")
    release.set_defaults(func=command_release_candidate)

    seal = sub.add_parser("seal", help="seal a visually reviewed candidate")
    seal.add_argument("config")
    seal.add_argument("--candidate", required=True)
    seal.add_argument("--review", required=True)
    seal.set_defaults(func=command_seal)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
    except GateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
