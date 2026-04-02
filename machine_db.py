"""Build a proper machine topology from the SQLite EPLAN snapshot.

The topology is derived from the EPLAN naming convention:
  =FunctionGroup+Location-DeviceTag

Devices are grouped by physical location (e.g., A1, A2, B1, B2).
Cables connect between locations (field stations ↔ control cabinets).
Function groups identify logical circuits spanning multiple locations.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MACHINE_DB_PATH = Path(__file__).parent / "eplan_exports.db"

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


def _format_cable_spec(row: sqlite3.Row) -> str:
    parts: list[str] = []
    conductor_count = row["conductor_count_hint"] or row["wire_count"]
    if conductor_count:
        parts.append(f"{conductor_count} Adern")
    hints_json = row["cross_section_hints_json"]
    if hints_json:
        hints = json.loads(hints_json)
        if len(hints) > 1:
            parts.append("/".join(f"{v:g}" for v in hints) + " mm\u00b2")
        elif hints:
            parts.append(f"{hints[0]:g} mm\u00b2")
    elif row["cross_section_mm2"]:
        parts.append(f"{row['cross_section_mm2']:g} mm\u00b2")
    if row["length_m"]:
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
# Build the machine graph
# ---------------------------------------------------------------------------

def build_machine_graph_from_db(
    db_path: str | Path = DEFAULT_MACHINE_DB_PATH,
) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite snapshot not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        dataset_info = conn.execute(
            "SELECT * FROM dataset_info WHERE id = 1"
        ).fetchone()
        if dataset_info is None:
            raise ValueError("SQLite snapshot does not contain dataset_info.")

        # Load all main device functions (excluding cable/terminal noise)
        device_rows = conn.execute(
            """
            SELECT id, name, category, is_main_function,
                   function_definition, function_type,
                   location, mounting_location, part_nr,
                   description, visible_name,
                   page_name, page_full_name, function_text
            FROM functions
            WHERE is_main_function = 1
            ORDER BY source_index
            """
        ).fetchall()

        # Load cables
        cable_rows = conn.execute(
            """
            SELECT id, name, type, cross_section_raw, cross_section_mm2,
                   length_m, article_description, article_part_nr,
                   wire_count, conductor_count_hint, cross_section_hints_json
            FROM cables
            ORDER BY source_index
            """
        ).fetchall()
    finally:
        conn.close()

    # ------------------------------------------------------------------
    # 1. Parse devices – build lookup structures
    # ------------------------------------------------------------------
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
            or _pick_localized_text(row["description"])
            or _pick_localized_text(row["function_text"])
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
            "visible_name": row["visible_name"] or "",
            "part_nr": row["part_nr"] or "",
            "technical_specs": row["function_type"] or row["function_definition"] or "",
            "page_ref": row["page_name"] or row["page_full_name"] or "",
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
            row["type"]
            or _pick_localized_text(row["article_description"])
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
            "cross_section_mm2": row["cross_section_mm2"],
            "num_cores": row["conductor_count_hint"] or row["wire_count"],
            "length_m": row["length_m"],
            "article_part_nr": row["article_part_nr"] or "",
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
    imported_at = dataset_info["imported_at"]
    try:
        imported_formatted = datetime.fromisoformat(imported_at).strftime(
            "%d.%m.%Y %H:%M"
        )
    except (ValueError, TypeError):
        imported_formatted = imported_at or ""

    source_name = Path(dataset_info["source_dir"]).name or "EPLAN Snapshot"

    return {
        "technical_data": {
            "rated_voltage": "",
            "frequency": "",
            "control_voltage": "",
            "connected_load": f"{len(devices)} Geraete",
            "full_load_current": f"{len(cable_rows)} Kabel",
            "max_pre_fuse": "",
            "enclosure_type": f"{dataset_info['resolved_connections_count']}/{dataset_info['connections_count']} aufgeloest",
            "sccr": "",
            "model": source_name,
            "project": dataset_info["source_dir"],
            "article_no": "",
            "doc_no": db_path.name,
        },
        "components": components,
        "connections": connections,
        "subsystems": subsystems,
        "io_assignments": [],
        "warnings": [],
        "pages_analyzed": 0,
        "data_source": {
            "kind": "sqlite",
            "label": db_path.name,
            "source_dir": dataset_info["source_dir"],
            "imported_at": imported_at,
            "imported_at_formatted": imported_formatted,
            "functions_count": dataset_info["functions_count"],
            "cables_count": dataset_info["cables_count"],
            "connections_count": dataset_info["connections_count"],
            "resolved_connections_count": dataset_info["resolved_connections_count"],
        },
    }
