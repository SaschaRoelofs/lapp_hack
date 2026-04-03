"""Build a proper machine topology from the EPLAN JSON project export.

The topology is derived from the EPLAN naming convention:
  =FunctionGroup+Location-DeviceTag

Devices are grouped by physical location (e.g., A1, A2, B1, B2).
Cables connect between locations (field stations ↔ control cabinets).
Function groups identify logical circuits spanning multiple locations.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_JSON_PATH = Path(__file__).parent / "ProjektDaten_20260403_082320.json"

# Categories to skip – infrastructure nodes that clutter the graph
_SKIP_CATEGORIES = frozenset({
    "Cable",
    "Terminal",
    "PLCTerminal",
    "DeviceEndTerminal",
    "TerminalDefText",
    "BusBarDefText",
    "ConnectorDefText",
})

# Map EPLAN function categories → component types used in the frontend
_CATEGORY_TYPE: dict[str, str] = {
    "AnalogSensor": "sensor",
    "Blackbox": "controller",
    "CircuitBreaker": "protection",
    "Coil": "switch",
    "Converter": "transformer",
    "CurrentCircuitBreaker": "protection",
    "Lamp": "sensor",
    "LightBarrier": "sensor",
    "Motor": "motor",
    "MotorOverloadSwitch": "protection",
    "NoContact": "switch",
    "Overload": "protection",
    "PLCBox": "controller",
    "Plug": "assembly",
    "ProcessLockArmature": "switch",
    "ProcessPump": "motor",
    "ProcessPiping": "assembly",
    "ProcessVessel": "assembly",
    "ProcessVesselPipeQueue": "assembly",
    "SignalLamp": "sensor",
    "Socket": "assembly",
    "Source": "transformer",
    "Switch": "switch",
}

# German labels for EPLAN categories
_CATEGORY_LABEL: dict[str, str] = {
    "AnalogSensor": "Analogsensor",
    "Blackbox": "Blackbox",
    "CircuitBreaker": "Leistungsschalter",
    "Coil": "Schuetz",
    "Converter": "Frequenzumrichter",
    "CurrentCircuitBreaker": "Leitungsschutzschalter",
    "Lamp": "Leuchte",
    "LightBarrier": "Lichtschranke",
    "Motor": "Motor",
    "MotorOverloadSwitch": "Motorschutzschalter",
    "NoContact": "Oeffner",
    "Overload": "Ueberlastschutz",
    "PLCBox": "SPS-Baugruppe",
    "Plug": "Stecker",
    "ProcessLockArmature": "Ventil",
    "ProcessPump": "Pumpe",
    "ProcessPiping": "Rohrleitung",
    "ProcessVessel": "Behaelter",
    "ProcessVesselPipeQueue": "Behaelteranschluss",
    "SignalLamp": "Meldeleuchte",
    "Socket": "Steckdose",
    "Source": "Spannungsquelle",
    "Switch": "Schalter",
}

# Location labels for known location prefixes
_LOCATION_LABELS: dict[str, str] = {
    "A1": "Schaltschrank A1",
    "A2": "Schaltschrank A2",
    "B1": "Feldstation B1",
    "B1.X1": "Feldstation B1.X1",
    "B2": "Feldstation B2",
    "B2.X1": "Feldstation B2.X1",
    "B3": "Feldstation B3",
    "B3.X1": "Feldstation B3.X1",
    "B4": "Prozessstation B4",
    "C2": "Feldstation C2",
}

PREFERRED_LANGUAGES = ("de_DE", "de", "en_US", "en_EN", "en")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _pick_localized_text(raw: str | None) -> str:
    """Pick the best localized value from ``lang@text;`` format strings."""
    if not raw:
        return ""
    candidates: dict[str, str] = {}
    fallback: list[str] = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "@" not in chunk:
            fallback.append(chunk)
            continue
        language, text = chunk.split("@", 1)
        text = text.strip()
        if text:
            candidates[language.strip()] = text
            fallback.append(text)
    for language in PREFERRED_LANGUAGES:
        text = candidates.get(language)
        if text:
            return text
    return fallback[0] if fallback else raw.strip()


def _parse_eplan_id(name: str) -> tuple[str, str, str]:
    """Parse ``=FuncGroup+Location-DeviceTag`` into (fg, location, device_tag).

    Also handles ``+Location-DeviceTag`` (no function group)
    and ``=FG+-DeviceTag`` (empty location).
    """
    # =FG+Loc-Dev
    m = re.match(r"^=([^+]+)\+([^-]*)-(.+)$", name)
    if m:
        return m.group(1), m.group(2), m.group(3)
    # +Loc-Dev (no function group)
    m = re.match(r"^\+([^-]+)-(.+)$", name)
    if m:
        return "", m.group(1), m.group(2)
    return "", "", name


def _parse_cable_location(cable_name: str) -> tuple[str, str]:
    """Parse ``+Location-Wxxx`` into (location, cable_suffix)."""
    m = re.match(r"^\+([^-]+)-(.+)$", cable_name)
    if m:
        return m.group(1), m.group(2)
    return "", cable_name


def _format_cable_spec(row: dict[str, Any]) -> str:
    parts: list[str] = []
    conductor_count = row.get("conductor_count_hint") or row.get("wire_count")
    if conductor_count:
        parts.append(f"{conductor_count} Adern")
    hints = row.get("cross_section_hints", [])
    if hints:
        if len(hints) > 1:
            parts.append("/".join(f"{v:g}" for v in hints) + " mm\u00b2")
        elif hints:
            parts.append(f"{hints[0]:g} mm\u00b2")
    elif row.get("cross_section_mm2"):
        parts.append(f"{row['cross_section_mm2']:g} mm\u00b2")
    if row.get("length_m"):
        parts.append(f"{row['length_m']:g} m")
    return " | ".join(parts)


def _subsystem_sort_key(name: str) -> tuple[Any, ...]:
    parts = re.split(r"([0-9]+)", name)
    key: list[Any] = []
    for part in parts:
        if not part:
            continue
        key.append(int(part) if part.isdigit() else part)
    return tuple(key)


# ---------------------------------------------------------------------------
# JSON cable/length parsing helpers
# ---------------------------------------------------------------------------

def _parse_german_float(raw: str | None) -> float | None:
    """Parse a German-locale float like ``2,472 m`` → 2.472."""
    if not raw:
        return None
    cleaned = re.sub(r"[^\d,.\-]", "", raw.strip())
    if not cleaned:
        return None
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_wires_and_cross_section(spec: str) -> tuple[int | None, list[float]]:
    """Parse ``wiresAndCrossSection`` like ``3G1,5`` or ``6G2,5/0,75``.

    Returns (conductor_count_hint, cross_section_hints).
    """
    if not spec:
        return None, []
    # Split on '/' for multi-section cables like "6G2,5/0,75"
    segments = spec.split("/")
    conductor_count: int | None = None
    hints: list[float] = []

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(r"(\d+)\s*[GgXx]\s*(.+)", seg)
        if m:
            count = int(m.group(1))
            cs_raw = m.group(2).replace(",", ".")
            if conductor_count is None:
                conductor_count = count
            try:
                hints.append(float(cs_raw))
            except ValueError:
                pass
        else:
            # Bare cross section like "0,75"
            cs_raw = seg.replace(",", ".")
            try:
                hints.append(float(cs_raw))
            except ValueError:
                pass
    return conductor_count, hints


def _parse_cable_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON cable object into the normalized format used by the graph builder."""
    cross_section_mm2 = _parse_german_float(raw.get("crossSection"))
    length_m = _parse_german_float(raw.get("length"))
    wire_count = raw.get("wireCount", 0) or 0

    conductor_count_hint, cross_section_hints = _parse_wires_and_cross_section(
        raw.get("wiresAndCrossSection", "")
    )

    # If wiresAndCrossSection gave us the real cross section, prefer it
    if cross_section_hints and cross_section_mm2 is None:
        cross_section_mm2 = cross_section_hints[0]
    elif cross_section_hints and cross_section_mm2 is not None:
        # The raw "crossSection" field often lacks the decimal (e.g. "15" means 1.5)
        # Trust the parsed cross section from wiresAndCrossSection
        cross_section_mm2 = cross_section_hints[0]

    # usedWires = number of actually loaded conductors (e.g. 3 of 5 wires used)
    used_wires_raw = raw.get("usedWires")
    used_wires: int | None = None
    if used_wires_raw is not None:
        try:
            used_wires = int(used_wires_raw)
        except (ValueError, TypeError):
            pass

    return {
        "name": raw["name"],
        "type": raw.get("type", ""),
        "cross_section_mm2": cross_section_mm2,
        "length_m": length_m,
        "article_description": raw.get("articleDescription", ""),
        "article_part_nr": raw.get("articlePartNr", ""),
        "wire_count": wire_count,
        "conductor_count_hint": conductor_count_hint,
        "cross_section_hints": cross_section_hints,
        "used_wires": used_wires,
    }


# ---------------------------------------------------------------------------
# Build the machine graph
# ---------------------------------------------------------------------------

def build_machine_graph_from_json(
    json_path: str | Path = DEFAULT_JSON_PATH,
) -> dict[str, Any]:
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON export not found: {json_path}")

    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    # Filter main functions
    device_rows = [
        fn for fn in data.get("functions", [])
        if fn.get("isMainFunction") == "True"
    ]
    raw_cables = data.get("cables", [])
    raw_connections = data.get("connections", [])

    # ------------------------------------------------------------------
    # 1. Parse devices – build lookup structures
    # ------------------------------------------------------------------
    # Parse cables from JSON into normalized dicts
    cable_rows = [_parse_cable_json(c) for c in raw_cables]

    devices: list[dict[str, Any]] = []
    fg_locations: dict[str, set[str]] = defaultdict(set)  # FG → {locations}

    for row in device_rows:
        if row["category"] in _SKIP_CATEGORIES:
            continue

        fg, loc, dev_tag = _parse_eplan_id(row["name"])
        if not loc:
            loc = "Prozess"

        if fg:
            fg_locations[fg].add(loc)

        category = row["category"]
        description = (
            _CATEGORY_LABEL.get(category, "")
            or _pick_localized_text(row.get("description", ""))
            or _pick_localized_text(row.get("functionText", ""))
            or category
        )

        devices.append({
            "name": row["name"],
            "fg": fg,
            "location": loc,
            "dev_tag": dev_tag,
            "category": category,
            "component_type": _CATEGORY_TYPE.get(category, "assembly"),
            "description": description,
            "visible_name": row.get("visibleName") or "",
            "part_nr": row.get("partNr") or "",
            "technical_specs": row.get("functionType") or row.get("functionDefinition") or "",
            "page_ref": row.get("pageName") or row.get("pageFullName") or "",
        })

    # ------------------------------------------------------------------
    # 2. Group devices by location → subsystems
    # ------------------------------------------------------------------
    devices_by_location: dict[str, list[dict]] = defaultdict(list)
    for d in devices:
        devices_by_location[d["location"]].append(d)

    all_locations = sorted(devices_by_location.keys(), key=_subsystem_sort_key)

    # ------------------------------------------------------------------
    # 3. Parse cables and infer routing
    # ------------------------------------------------------------------

    # Build FG→location pairs (multi-location function groups)
    # For cable routing: field location → which cabinet location is linked?
    field_to_cabinet: dict[str, str] = {}
    for fg, locs in fg_locations.items():
        cabinet_locs = sorted(l for l in locs if l.startswith("A"))
        field_locs = sorted(l for l in locs if l and not l.startswith("A"))
        for fl in field_locs:
            if fl not in field_to_cabinet and cabinet_locs:
                # Prefer A2 (main PLC cabinet) if available, else A1
                field_to_cabinet[fl] = (
                    "A2" if "A2" in cabinet_locs else cabinet_locs[0]
                )

    # Default: any remaining field location → A2
    for loc in all_locations:
        if loc not in field_to_cabinet and not loc.startswith("A") and loc != "Prozess":
            field_to_cabinet[loc] = "A2"

    # Cabinet → field station mapping (for A-side cables)
    cabinet_to_fields: dict[str, list[str]] = defaultdict(list)
    for fg, locs in fg_locations.items():
        cabinet_locs = sorted(l for l in locs if l.startswith("A"))
        field_locs = sorted(l for l in locs if l and not l.startswith("A"))
        for cl in cabinet_locs:
            for fl in field_locs:
                if fl not in cabinet_to_fields[cl]:
                    cabinet_to_fields[cl].append(fl)

    # Collect cable locations that exist in the DB
    cable_location_set: set[str] = set()
    for row in cable_rows:
        loc, _ = _parse_cable_location(row["name"])
        cable_location_set.add(loc)

    def _infer_cabinet_cable_destination(
        cab_loc: str, cable_suffix: str,
    ) -> str:
        """Heuristic: match cabinet cable suffix to a field station.

        WD (data) cables route to .X1 sub-stations, WG (power) cables
        route to the parent field station.  If a matching field location
        has its own cable with the same suffix, use that as the partner.
        """
        fields = cabinet_to_fields.get(cab_loc, [])
        if not fields:
            return ""
        # Try to find a field location that has a cable with the same suffix
        for fl in fields:
            partner = f"+{fl}-{cable_suffix}"
            if partner in _cable_names:
                return fl
        # WD → prefer .X1 stations; WG → prefer base stations
        if cable_suffix.startswith("WD") or cable_suffix.startswith("WZ"):
            x1_fields = [f for f in fields if ".X1" in f]
            if x1_fields:
                return x1_fields[0]
        elif cable_suffix.startswith("WG"):
            base_fields = [f for f in fields if ".X1" not in f]
            if base_fields:
                return base_fields[0]
        return fields[0]

    _cable_names = {row["name"] for row in cable_rows}

    cables: list[dict[str, Any]] = []
    for row in cable_rows:
        cable_loc, cable_suffix = _parse_cable_location(row["name"])
        cable_type = (
            row.get("type")
            or _pick_localized_text(row.get("article_description"))
            or "Kabel"
        )
        cable_spec = _format_cable_spec(row)

        # Determine src/dst locations
        src_loc = cable_loc
        if src_loc.startswith("A"):
            dst_loc = _infer_cabinet_cable_destination(src_loc, cable_suffix)
        else:
            dst_loc = field_to_cabinet.get(src_loc, "A2")

        cables.append({
            "cable_name": row["name"],
            "cable_type": cable_type,
            "cable_spec": cable_spec,
            "cross_section_mm2": row.get("cross_section_mm2"),
            "num_cores": row.get("conductor_count_hint") or row.get("wire_count"),
            "used_wires": row.get("used_wires"),
            "length_m": row.get("length_m"),
            "article_part_nr": row.get("article_part_nr") or "",
            "src_loc": src_loc,
            "dst_loc": dst_loc,
        })

    # ------------------------------------------------------------------
    # 4. Build component nodes
    # ------------------------------------------------------------------
    components: list[dict[str, Any]] = []

    for d in devices:
        comp = {
            "id": d["name"],
            "designation": d["dev_tag"],
            "component_type": d["component_type"],
            "description_de": d["description"],
            "description_en": d["category"],
            "manufacturer": "",
            "order_number": d["part_nr"],
            "technical_specs": d["technical_specs"],
            "sap_number": "",
            "location": f"+{d['location']}" if d["location"] != "Prozess" else "",
            "subsystem": d["location"],
            "page_ref": d["page_ref"],
            "quantity": 1,
            "source_category": d["category"],
            "function_group": d["fg"],
            "full_eplan_name": d["name"],
            "related_cables": [],
            "io_assignments": [],
        }
        components.append(comp)

    # ------------------------------------------------------------------
    # 5. Build connection edges (cables between locations)
    # ------------------------------------------------------------------
    connections: list[dict[str, Any]] = []

    for cable in cables:
        src_loc = cable["src_loc"]
        dst_loc = cable["dst_loc"]

        if not src_loc or not dst_loc:
            continue

        from_id = f"loc:{src_loc}"
        to_id = f"loc:{dst_loc}"

        connections.append({
            "cable_name": cable["cable_name"],
            "cable_type": cable["cable_type"],
            "cable_spec": cable["cable_spec"],
            "cross_section_mm2": cable["cross_section_mm2"],
            "num_cores": cable["num_cores"],
            "used_wires": cable["used_wires"],
            "from_component": from_id,
            "to_component": to_id,
            "from_location": src_loc,
            "to_location": dst_loc,
            "connection_type": "cable",
            "function_de": cable["cable_type"],
            "function_en": cable["cable_type"],
            "sap_number": cable["article_part_nr"],
            "length_m": cable["length_m"],
            "page_ref": "",
        })

    # Attach cable summaries to devices at matching locations
    cables_by_location: dict[str, list[dict]] = defaultdict(list)
    for cable in cables:
        summary = {
            "cable_name": cable["cable_name"],
            "cable_type": cable["cable_type"],
            "cable_spec": cable["cable_spec"],
            "cross_section_mm2": cable["cross_section_mm2"],
            "num_cores": cable["num_cores"],
            "used_wires": cable["used_wires"],
            "length_m": cable["length_m"],
            "sap_number": cable["article_part_nr"],
            "function_de": cable["cable_type"],
            "function_en": cable["cable_type"],
        }
        cables_by_location[cable["src_loc"]].append(summary)
        if cable["dst_loc"] and cable["dst_loc"] != cable["src_loc"]:
            cables_by_location[cable["dst_loc"]].append(summary)

    for comp in components:
        comp["related_cables"] = cables_by_location.get(comp["subsystem"], [])

    # ------------------------------------------------------------------
    # 5b. Build intra-subsystem connections (function-group chains)
    # ------------------------------------------------------------------
    # Devices sharing the same function group within a location form a
    # logical circuit chain.  We connect them sequentially so the graph
    # shows local device relationships.
    fg_loc_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in devices:
        if d["fg"]:
            fg_loc_groups[(d["fg"], d["location"])].append(d)

    for (fg, loc), group_devs in fg_loc_groups.items():
        if len(group_devs) < 2:
            continue
        # Sort by device tag for a stable chain order
        group_devs.sort(key=lambda d: d["dev_tag"])
        for i in range(len(group_devs) - 1):
            a = group_devs[i]
            b = group_devs[i + 1]
            connections.append({
                "cable_name": "",
                "cable_type": "",
                "cable_spec": "",
                "cross_section_mm2": None,
                "num_cores": None,
                "from_component": a["name"],
                "to_component": b["name"],
                "from_location": loc,
                "to_location": loc,
                "connection_type": "fg_chain",
                "function_group": fg,
                "function_de": f"Funktionsgruppe {fg}",
                "function_en": f"Function group {fg}",
                "sap_number": "",
                "length_m": None,
                "page_ref": "",
            })

    # ------------------------------------------------------------------
    # 6. Build subsystem objects (= locations)
    # ------------------------------------------------------------------
    subsystems: list[dict[str, Any]] = []
    for loc in all_locations:
        loc_devices = devices_by_location[loc]
        comp_ids = [d["name"] for d in loc_devices]
        loc_label = _LOCATION_LABELS.get(loc, loc)
        loc_cables = cables_by_location.get(loc, [])

        subsystems.append({
            "name": loc,
            "name_de": loc_label,
            "name_en": loc,
            "page_ref": 0,
            "component_ids": comp_ids,
            "cable_count": len(loc_cables),
        })

    # ------------------------------------------------------------------
    # 7. Assemble final payload
    # ------------------------------------------------------------------
    timestamp_raw = data.get("timestamp", "")
    try:
        imported_dt = datetime.strptime(timestamp_raw, "%Y%m%d_%H%M%S")
        imported_at = imported_dt.isoformat()
        imported_formatted = imported_dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        imported_at = timestamp_raw
        imported_formatted = timestamp_raw

    project_name = data.get("projectName", "EPLAN Export")
    project_path = data.get("projectPath", "")

    # Count resolved connections (those with non-trivial from/to)
    resolved_connections_count = sum(
        1 for c in raw_connections
        if c.get("from", "+") != "+" and c.get("to", "+") != "+"
    )

    return {
        "technical_data": {
            "project_name": project_name,
            "export_date": imported_formatted,
            "functions_total": data.get("functionCount", len(device_rows)),
            "devices_count": len(devices),
            "cables_count": len(cable_rows),
            "connections_info": f"{resolved_connections_count} / {len(raw_connections)} aufgel\u00f6st",
            "subsystems_count": len(subsystems),
        },
        "components": components,
        "connections": connections,
        "subsystems": subsystems,
        "io_assignments": [],
        "warnings": [],
        "pages_analyzed": 0,
        "data_source": {
            "kind": "json",
            "label": json_path.name,
            "source_dir": project_path,
            "imported_at": imported_at,
            "imported_at_formatted": imported_formatted,
            "functions_count": data.get("functionCount", len(device_rows)),
            "cables_count": data.get("cableCount", len(raw_cables)),
            "connections_count": data.get("connectionCount", len(raw_connections)),
            "resolved_connections_count": resolved_connections_count,
        },
    }
