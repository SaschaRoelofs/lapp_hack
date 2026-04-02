"""SQLite persistence for parsed EPLAN export data."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

from eplan_exports import CableWire, ConnectionRecord, EplanExportBundle, load_export_bundle


DEFAULT_DB_PATH = Path(__file__).parent / "eplan_exports.db"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dataset_info (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    source_dir TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    functions_count INTEGER NOT NULL,
    cables_count INTEGER NOT NULL,
    connections_count INTEGER NOT NULL,
    resolved_connections_count INTEGER NOT NULL,
    unresolved_connections_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS functions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_index INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    is_main_function INTEGER NOT NULL,
    identifying_name TEXT,
    function_definition TEXT,
    function_type TEXT,
    location TEXT,
    mounting_location TEXT,
    mounting_site TEXT,
    installation_space TEXT,
    part_nr TEXT,
    description TEXT,
    visible_name TEXT,
    page_name TEXT,
    page_full_name TEXT,
    function_text TEXT,
    supplementary_field_1 TEXT,
    supplementary_field_2 TEXT
);

CREATE TABLE IF NOT EXISTS cables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_index INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    type TEXT,
    cross_section_raw TEXT,
    cross_section_mm2 REAL,
    wires_and_cross_section TEXT,
    length_raw TEXT,
    length_m REAL,
    used_wires_raw TEXT,
    used_wires_count INTEGER,
    current_capacity TEXT,
    rated_voltage TEXT,
    article_description TEXT,
    article_part_nr TEXT,
    wire_count INTEGER NOT NULL,
    conductor_count_hint INTEGER,
    cross_section_hints_json TEXT NOT NULL DEFAULT '[]',
    primary_function_id INTEGER REFERENCES functions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS cable_function_links (
    cable_id INTEGER NOT NULL REFERENCES cables(id) ON DELETE CASCADE,
    function_id INTEGER NOT NULL REFERENCES functions(id) ON DELETE CASCADE,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (cable_id, function_id)
);

CREATE TABLE IF NOT EXISTS cable_wires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cable_id INTEGER NOT NULL REFERENCES cables(id) ON DELETE CASCADE,
    source_index INTEGER NOT NULL,
    wire_number TEXT,
    cross_section_raw TEXT,
    cross_section_mm2 REAL,
    wire_length_raw TEXT,
    wire_length_m REAL,
    from_endpoint TEXT,
    to_endpoint TEXT,
    wire_color TEXT,
    color_number TEXT,
    potential TEXT,
    signal_name TEXT,
    UNIQUE (cable_id, source_index)
);

CREATE TABLE IF NOT EXISTS connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_index INTEGER NOT NULL UNIQUE,
    name TEXT,
    identifying_name TEXT,
    from_endpoint TEXT,
    to_endpoint TEXT,
    wire_number TEXT,
    cross_section_raw TEXT,
    cross_section_mm2 REAL,
    wire_length_raw TEXT,
    wire_length_m REAL,
    wire_color TEXT,
    color_number TEXT,
    potential TEXT,
    signal_name TEXT,
    connection_type TEXT,
    cable_name TEXT,
    cable_type TEXT,
    matched_cable_id INTEGER REFERENCES cables(id) ON DELETE SET NULL,
    matched_wire_id INTEGER REFERENCES cable_wires(id) ON DELETE SET NULL,
    resolution_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connection_def_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    source_index INTEGER NOT NULL,
    identifying_name TEXT,
    wire_number TEXT,
    cross_section_raw TEXT,
    cross_section_mm2 REAL,
    wire_length_raw TEXT,
    wire_length_m REAL,
    wire_color TEXT,
    color_number TEXT,
    potential TEXT,
    signal_name TEXT,
    UNIQUE (connection_id, source_index)
);

CREATE TABLE IF NOT EXISTS connection_resolution_reasons (
    connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    PRIMARY KEY (connection_id, reason)
);

CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name);
CREATE INDEX IF NOT EXISTS idx_functions_category ON functions(category);
CREATE INDEX IF NOT EXISTS idx_cables_primary_function_id ON cables(primary_function_id);
CREATE INDEX IF NOT EXISTS idx_cable_wires_lookup ON cable_wires(cable_id, wire_number);
CREATE INDEX IF NOT EXISTS idx_connections_cable_name ON connections(cable_name);
CREATE INDEX IF NOT EXISTS idx_connections_matched_cable_id ON connections(matched_cable_id);
CREATE INDEX IF NOT EXISTS idx_connections_matched_wire_id ON connections(matched_wire_id);
CREATE INDEX IF NOT EXISTS idx_connection_def_points_connection_id ON connection_def_points(connection_id);
"""


@dataclass(slots=True)
class ImportSummary:
    db_path: Path
    source_dir: Path
    functions_count: int
    cables_count: int
    connections_count: int
    resolved_connections_count: int
    unresolved_connections_count: int


def connect_eplan_db(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(db_path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def clear_snapshot(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM connection_resolution_reasons")
    conn.execute("DELETE FROM connection_def_points")
    conn.execute("DELETE FROM connections")
    conn.execute("DELETE FROM cable_wires")
    conn.execute("DELETE FROM cable_function_links")
    conn.execute("DELETE FROM cables")
    conn.execute("DELETE FROM functions")
    conn.execute("DELETE FROM dataset_info")


def _pick_primary_function_id(function_ids: list[int], main_flags: list[bool]) -> int | None:
    for function_id, is_main in zip(function_ids, main_flags, strict=False):
        if is_main:
            return function_id
    return function_ids[0] if function_ids else None


def _choose_wire_id(
    connection: ConnectionRecord,
    candidate_wire_ids: list[int],
    wire_lookup: dict[int, dict[str, str | float | None]],
) -> int | None:
    if not candidate_wire_ids:
        return None
    if len(candidate_wire_ids) == 1:
        return candidate_wire_ids[0]

    def score(wire_id: int) -> tuple[int, int, int, int]:
        wire = wire_lookup[wire_id]
        return (
            int(wire["wire_length_raw"] == connection.wire_length_raw),
            int(wire["cross_section_raw"] == connection.cross_section_raw),
            int(wire["from_endpoint"] == connection.from_endpoint),
            int(wire["to_endpoint"] == connection.to_endpoint),
        )

    return max(candidate_wire_ids, key=score)


def import_bundle_to_sqlite(
    bundle: EplanExportBundle,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ImportSummary:
    db_path = Path(db_path)
    resolved_connections = bundle.resolve_connections()
    cable_functions_by_name = bundle.functions.cable_functions_by_name()

    conn = connect_eplan_db(db_path)
    try:
        with conn:
            initialize_schema(conn)
            clear_snapshot(conn)

            function_id_by_source_index: dict[int, int] = {}
            function_id_by_name: dict[str, list[int]] = {}
            function_main_flags_by_name: dict[str, list[bool]] = {}

            for source_index, function in enumerate(bundle.functions.functions):
                cursor = conn.execute(
                    """
                    INSERT INTO functions (
                        source_index, name, category, is_main_function,
                        identifying_name, function_definition, function_type,
                        location, mounting_location, mounting_site, installation_space,
                        part_nr, description, visible_name, page_name, page_full_name,
                        function_text, supplementary_field_1, supplementary_field_2
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_index,
                        function.name,
                        function.category.value,
                        int(function.is_main_function),
                        function.identifying_name,
                        function.function_definition,
                        function.function_type,
                        function.location,
                        function.mounting_location,
                        function.mounting_site,
                        function.installation_space,
                        function.part_nr,
                        function.description,
                        function.visible_name,
                        function.page_name,
                        function.page_full_name,
                        function.function_text,
                        function.supplementary_field_1,
                        function.supplementary_field_2,
                    ),
                )
                function_id = int(cursor.lastrowid)
                function_id_by_source_index[source_index] = function_id
                function_id_by_name.setdefault(function.name, []).append(function_id)
                function_main_flags_by_name.setdefault(function.name, []).append(function.is_main_function)

            cable_id_by_name: dict[str, int] = {}
            wire_ids_by_key: dict[tuple[str, str], list[int]] = {}
            wire_lookup: dict[int, dict[str, str | float | None]] = {}

            for source_index, cable in enumerate(bundle.cables.cables):
                linked_functions = cable_functions_by_name.get(cable.name, [])
                linked_function_ids = function_id_by_name.get(cable.name, [])
                linked_function_main_flags = function_main_flags_by_name.get(cable.name, [])
                primary_function_id = _pick_primary_function_id(linked_function_ids, linked_function_main_flags)

                cursor = conn.execute(
                    """
                    INSERT INTO cables (
                        source_index, name, type, cross_section_raw, cross_section_mm2,
                        wires_and_cross_section, length_raw, length_m, used_wires_raw,
                        used_wires_count, current_capacity, rated_voltage,
                        article_description, article_part_nr, wire_count,
                        conductor_count_hint, cross_section_hints_json, primary_function_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_index,
                        cable.name,
                        cable.type,
                        cable.cross_section_raw,
                        cable.cross_section_mm2,
                        cable.wires_and_cross_section,
                        cable.length_raw,
                        cable.length_m,
                        cable.used_wires_raw,
                        cable.used_wires_count,
                        cable.current_capacity,
                        cable.rated_voltage,
                        cable.article_description,
                        cable.article_part_nr,
                        cable.wire_count,
                        cable.conductor_count_hint,
                        json.dumps(list(cable.cross_section_hints_mm2)),
                        primary_function_id,
                    ),
                )
                cable_id = int(cursor.lastrowid)
                cable_id_by_name[cable.name] = cable_id

                for function, function_id in zip(linked_functions, linked_function_ids, strict=False):
                    conn.execute(
                        "INSERT INTO cable_function_links (cable_id, function_id, is_primary) VALUES (?, ?, ?)",
                        (cable_id, function_id, int(function_id == primary_function_id and function.is_main_function)),
                    )

                for wire_index, wire in enumerate(cable.wires):
                    wire_cursor = conn.execute(
                        """
                        INSERT INTO cable_wires (
                            cable_id, source_index, wire_number, cross_section_raw, cross_section_mm2,
                            wire_length_raw, wire_length_m, from_endpoint, to_endpoint,
                            wire_color, color_number, potential, signal_name
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cable_id,
                            wire_index,
                            wire.wire_number,
                            wire.cross_section_raw,
                            wire.cross_section_mm2,
                            wire.wire_length_raw,
                            wire.wire_length_m,
                            wire.from_endpoint,
                            wire.to_endpoint,
                            wire.wire_color,
                            wire.color_number,
                            wire.potential,
                            wire.signal_name,
                        ),
                    )
                    wire_id = int(wire_cursor.lastrowid)
                    if wire.wire_number:
                        wire_ids_by_key.setdefault((cable.name, wire.wire_number), []).append(wire_id)
                    wire_lookup[wire_id] = {
                        "wire_length_raw": wire.wire_length_raw,
                        "cross_section_raw": wire.cross_section_raw,
                        "from_endpoint": wire.from_endpoint,
                        "to_endpoint": wire.to_endpoint,
                    }

            for source_index, connection in enumerate(bundle.connections.connections):
                resolution = resolved_connections[source_index]
                matched_cable_id = cable_id_by_name.get(resolution.matched_cable_name or "")
                matched_wire_id = None
                if resolution.matched_cable_name and resolution.effective_wire_number:
                    matched_wire_id = _choose_wire_id(
                        connection=connection,
                        candidate_wire_ids=wire_ids_by_key.get(
                            (resolution.matched_cable_name, resolution.effective_wire_number),
                            [],
                        ),
                        wire_lookup=wire_lookup,
                    )

                cursor = conn.execute(
                    """
                    INSERT INTO connections (
                        source_index, name, identifying_name, from_endpoint, to_endpoint,
                        wire_number, cross_section_raw, cross_section_mm2,
                        wire_length_raw, wire_length_m, wire_color, color_number,
                        potential, signal_name, connection_type, cable_name, cable_type,
                        matched_cable_id, matched_wire_id, resolution_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_index,
                        connection.name,
                        connection.identifying_name,
                        connection.from_endpoint,
                        connection.to_endpoint,
                        connection.wire_number,
                        connection.cross_section_raw,
                        connection.cross_section_mm2,
                        connection.wire_length_raw,
                        connection.wire_length_m,
                        connection.wire_color,
                        connection.color_number,
                        connection.potential,
                        connection.signal_name,
                        connection.connection_type,
                        connection.cable,
                        connection.cable_type,
                        matched_cable_id,
                        matched_wire_id,
                        "resolved" if resolution.is_resolved else "unresolved",
                    ),
                )
                connection_id = int(cursor.lastrowid)

                for def_point_index, def_point in enumerate(connection.connection_def_points):
                    conn.execute(
                        """
                        INSERT INTO connection_def_points (
                            connection_id, source_index, identifying_name, wire_number,
                            cross_section_raw, cross_section_mm2, wire_length_raw,
                            wire_length_m, wire_color, color_number, potential, signal_name
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            connection_id,
                            def_point_index,
                            def_point.identifying_name,
                            def_point.wire_number,
                            def_point.cross_section_raw,
                            def_point.cross_section_mm2,
                            def_point.wire_length_raw,
                            def_point.wire_length_m,
                            def_point.wire_color,
                            def_point.color_number,
                            def_point.potential,
                            def_point.signal_name,
                        ),
                    )

                for reason in resolution.unresolved_reasons:
                    conn.execute(
                        "INSERT INTO connection_resolution_reasons (connection_id, reason) VALUES (?, ?)",
                        (connection_id, reason),
                    )

            conn.execute(
                """
                INSERT INTO dataset_info (
                    id, source_dir, imported_at, functions_count, cables_count,
                    connections_count, resolved_connections_count, unresolved_connections_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    str(bundle.base_path or ""),
                    datetime.now(UTC).isoformat(),
                    len(bundle.functions.functions),
                    len(bundle.cables.cables),
                    len(bundle.connections.connections),
                    sum(1 for item in resolved_connections if item.is_resolved),
                    sum(1 for item in resolved_connections if not item.is_resolved),
                ),
            )
    finally:
        conn.close()

    return ImportSummary(
        db_path=db_path,
        source_dir=bundle.base_path or Path(),
        functions_count=len(bundle.functions.functions),
        cables_count=len(bundle.cables.cables),
        connections_count=len(bundle.connections.connections),
        resolved_connections_count=sum(1 for item in resolved_connections if item.is_resolved),
        unresolved_connections_count=sum(1 for item in resolved_connections if not item.is_resolved),
    )


def import_directory_to_sqlite(
    source_dir: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ImportSummary:
    bundle = load_export_bundle(source_dir)
    return import_bundle_to_sqlite(bundle=bundle, db_path=db_path)
