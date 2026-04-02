"""Pydantic models and loaders for EPLAN export JSON files."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalize_optional_text(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _parse_float_text(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:[,.]\d+)?", value)
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def _parse_int_text(value: str | None) -> int | None:
    parsed = _parse_float_text(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _parse_localized_text(raw_value: str | None) -> dict[str, str]:
    if not raw_value:
        return {}

    values: dict[str, str] = {}
    for chunk in raw_value.split(";"):
        chunk = chunk.strip()
        if not chunk or "@" not in chunk:
            continue
        language, text = chunk.split("@", 1)
        language = language.strip()
        text = text.strip()
        if language and text:
            values[language] = text
    return values


def _parse_wire_pattern(raw_value: str | None) -> tuple[int | None, tuple[float, ...]]:
    if not raw_value:
        return None, ()

    match = re.match(r"^\s*(\d+)\s*[xXGg]\s*(.+?)\s*$", raw_value)
    if not match:
        return None, ()

    conductor_count = int(match.group(1))
    suffix = match.group(2)
    sizes: list[float] = []
    for part in suffix.split("/"):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"\d+(?:,\d+)?", part):
            sizes.append(float(part.replace(",", ".")))
    return conductor_count, tuple(sizes)


def _parse_unambiguous_cross_section(raw_value: str | None) -> float | None:
    if not raw_value:
        return None

    normalized = raw_value.strip()
    if not normalized:
        return None
    if "," in normalized or "." in normalized:
        return float(normalized.replace(",", "."))
    if re.fullmatch(r"\d", normalized):
        return float(normalized)
    return None


def _is_placeholder_designator(value: str | None) -> bool:
    return value is None or value in {"", "+"}


class ExportModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", str_strip_whitespace=True)


class FunctionCategory(str, Enum):
    ANALOG_SENSOR = "AnalogSensor"
    BLACKBOX = "Blackbox"
    BUSBAR = "Busbar"
    BUSBAR_DEF_TEXT = "BusBarDefText"
    CABLE = "Cable"
    CIRCUIT_BREAKER = "CircuitBreaker"
    COIL = "Coil"
    CONNECTOR_DEF_TEXT = "ConnectorDefText"
    CONVERTER = "Converter"
    CURRENT_CIRCUIT_BREAKER = "CurrentCircuitBreaker"
    DEVICE_END_TERMINAL = "DeviceEndTerminal"
    LAMP = "Lamp"
    LIGHT_BARRIER = "LightBarrier"
    MOTOR = "Motor"
    MOTOR_OVERLOAD_SWITCH = "MotorOverloadSwitch"
    NC_CONTACT = "NcContact"
    NO_CONTACT = "NoContact"
    OVERLOAD = "Overload"
    PLC_BOX = "PLCBox"
    PLC_TERMINAL = "PLCTerminal"
    PLUG = "Plug"
    PROCESS_LOCK_ARMATURE = "ProcessLockArmature"
    PROCESS_PIPING = "ProcessPiping"
    PROCESS_PUMP = "ProcessPump"
    PROCESS_VESSEL = "ProcessVessel"
    PROCESS_VESSEL_PIPE_QUEUE = "ProcessVesselPipeQueue"
    PROCESS_VESSEL_TERMINAL = "ProcessVesselTerminal"
    RESISTOR = "Resistor"
    SHIELDING = "Shielding"
    SIGNAL_LAMP = "SignalLamp"
    SOCKET = "Socket"
    SOURCE = "Source"
    SWITCH = "Switch"
    TERMINAL = "Terminal"
    TERMINAL_DEF_TEXT = "TerminalDefText"


class FunctionRecord(ExportModel):
    name: str
    identifying_name: str | None = Field(default=None, alias="identifyingName")
    function_definition: str | None = Field(default=None, alias="functionDefinition")
    function_type: str | None = Field(default=None, alias="functionType")
    category: FunctionCategory
    is_main_function: bool = Field(alias="isMainFunction")
    location: str | None = None
    mounting_location: str | None = Field(default=None, alias="mountingLocation")
    mounting_site: str | None = Field(default=None, alias="mountingSite")
    installation_space: str | None = Field(default=None, alias="installationSpace")
    part_nr: str | None = Field(default=None, alias="partNr")
    description: str | None = None
    visible_name: str | None = Field(default=None, alias="visibleName")
    page_name: str | None = Field(default=None, alias="pageName")
    page_full_name: str | None = Field(default=None, alias="pageFullName")
    function_text: str | None = Field(default=None, alias="functionText")
    supplementary_field_1: str | None = Field(default=None, alias="supplementaryField1")
    supplementary_field_2: str | None = Field(default=None, alias="supplementaryField2")

    @field_validator(
        "identifying_name",
        "function_definition",
        "function_type",
        "location",
        "mounting_location",
        "mounting_site",
        "installation_space",
        "part_nr",
        "description",
        "visible_name",
        "page_name",
        "page_full_name",
        "function_text",
        "supplementary_field_1",
        "supplementary_field_2",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        return _normalize_optional_text(value)

    @field_validator("is_main_function", mode="before")
    @classmethod
    def _normalize_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        raise ValueError(f"Unsupported boolean value: {value!r}")

    @property
    def is_cable(self) -> bool:
        return self.category == FunctionCategory.CABLE


class FunctionsDocument(ExportModel):
    functions: list[FunctionRecord]

    def by_name(self) -> dict[str, list[FunctionRecord]]:
        grouped: dict[str, list[FunctionRecord]] = defaultdict(list)
        for function in self.functions:
            grouped[function.name].append(function)
        return dict(grouped)

    def cable_functions_by_name(self) -> dict[str, list[FunctionRecord]]:
        grouped: dict[str, list[FunctionRecord]] = defaultdict(list)
        for function in self.functions:
            if function.is_cable:
                grouped[function.name].append(function)
        return dict(grouped)

    def category_counts(self) -> dict[str, int]:
        return dict(Counter(function.category.value for function in self.functions))


class CableWire(ExportModel):
    wire_number: str | None = Field(default=None, alias="wireNumber")
    cross_section_raw: str | None = Field(default=None, alias="crossSection")
    wire_length_raw: str | None = Field(default=None, alias="wireLength")
    from_endpoint: str | None = Field(default=None, alias="from")
    to_endpoint: str | None = Field(default=None, alias="to")
    wire_color: str | None = Field(default=None, alias="wireColor")
    color_number: str | None = Field(default=None, alias="colorNumber")
    potential: str | None = None
    signal_name: str | None = Field(default=None, alias="signalName")
    cross_section_mm2: float | None = None
    wire_length_m: float | None = None

    @field_validator(
        "wire_number",
        "cross_section_raw",
        "wire_length_raw",
        "from_endpoint",
        "to_endpoint",
        "wire_color",
        "color_number",
        "potential",
        "signal_name",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _set_derived_fields(self) -> Self:
        self.cross_section_mm2 = _parse_unambiguous_cross_section(self.cross_section_raw)
        self.wire_length_m = _parse_float_text(self.wire_length_raw)
        return self


class CableRecord(ExportModel):
    name: str
    type: str | None = None
    cross_section_raw: str | None = Field(default=None, alias="crossSection")
    wires_and_cross_section: str | None = Field(default=None, alias="wiresAndCrossSection")
    length_raw: str | None = Field(default=None, alias="length")
    used_wires_raw: str | None = Field(default=None, alias="usedWires")
    current_capacity: str | None = Field(default=None, alias="currentCapacity")
    rated_voltage: str | None = Field(default=None, alias="ratedVoltage")
    article_description: str | None = Field(default=None, alias="articleDescription")
    article_part_nr: str | None = Field(default=None, alias="articlePartNr")
    wire_count: int = Field(alias="wireCount")
    wires: list[CableWire]
    cross_section_mm2: float | None = None
    length_m: float | None = None
    used_wires_count: int | None = None
    article_description_localized: dict[str, str] = Field(default_factory=dict)
    conductor_count_hint: int | None = None
    cross_section_hints_mm2: tuple[float, ...] = ()

    @field_validator(
        "type",
        "cross_section_raw",
        "wires_and_cross_section",
        "length_raw",
        "used_wires_raw",
        "current_capacity",
        "rated_voltage",
        "article_description",
        "article_part_nr",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _set_derived_fields(self) -> Self:
        self.cross_section_mm2 = _parse_unambiguous_cross_section(self.cross_section_raw)
        self.length_m = _parse_float_text(self.length_raw)
        self.used_wires_count = _parse_int_text(self.used_wires_raw)
        self.article_description_localized = _parse_localized_text(self.article_description)
        self.conductor_count_hint, self.cross_section_hints_mm2 = _parse_wire_pattern(self.wires_and_cross_section)
        if self.cross_section_mm2 is None and self.cross_section_hints_mm2:
            self.cross_section_mm2 = self.cross_section_hints_mm2[0]
        return self

    def wire_by_number(self) -> dict[str, list[CableWire]]:
        grouped: dict[str, list[CableWire]] = defaultdict(list)
        for wire in self.wires:
            if wire.wire_number:
                grouped[wire.wire_number].append(wire)
        return dict(grouped)


class CablesDocument(ExportModel):
    cable_count: int = Field(alias="cableCount")
    cables: list[CableRecord]

    @model_validator(mode="after")
    def _validate_count(self) -> Self:
        if self.cable_count != len(self.cables):
            raise ValueError(f"cableCount={self.cable_count} does not match cables={len(self.cables)}")
        return self

    def by_name(self) -> dict[str, CableRecord]:
        return {cable.name: cable for cable in self.cables}

    def wire_index(self) -> dict[tuple[str, str], list[CableWire]]:
        grouped: dict[tuple[str, str], list[CableWire]] = defaultdict(list)
        for cable in self.cables:
            for wire in cable.wires:
                if wire.wire_number:
                    grouped[(cable.name, wire.wire_number)].append(wire)
        return dict(grouped)


class ConnectionDefPoint(ExportModel):
    identifying_name: str | None = Field(default=None, alias="identifyingName")
    wire_number: str | None = Field(default=None, alias="wireNumber")
    cross_section_raw: str | None = Field(default=None, alias="crossSection")
    wire_length_raw: str | None = Field(default=None, alias="wireLength")
    wire_color: str | None = Field(default=None, alias="wireColor")
    color_number: str | None = Field(default=None, alias="colorNumber")
    potential: str | None = None
    signal_name: str | None = Field(default=None, alias="signalName")
    cross_section_mm2: float | None = None
    wire_length_m: float | None = None

    @field_validator(
        "identifying_name",
        "wire_number",
        "cross_section_raw",
        "wire_length_raw",
        "wire_color",
        "color_number",
        "potential",
        "signal_name",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _set_derived_fields(self) -> Self:
        self.cross_section_mm2 = _parse_unambiguous_cross_section(self.cross_section_raw)
        self.wire_length_m = _parse_float_text(self.wire_length_raw)
        return self


class ConnectionRecord(ExportModel):
    name: str | None = None
    identifying_name: str | None = Field(default=None, alias="identifyingName")
    from_endpoint: str | None = Field(default=None, alias="from")
    to_endpoint: str | None = Field(default=None, alias="to")
    wire_number: str | None = Field(default=None, alias="wireNumber")
    cross_section_raw: str | None = Field(default=None, alias="crossSection")
    wire_length_raw: str | None = Field(default=None, alias="wireLength")
    wire_color: str | None = Field(default=None, alias="wireColor")
    color_number: str | None = Field(default=None, alias="colorNumber")
    potential: str | None = None
    signal_name: str | None = Field(default=None, alias="signalName")
    connection_type: str | None = Field(default=None, alias="connectionType")
    cable: str | None = None
    cable_type: str | None = Field(default=None, alias="cableType")
    connection_def_points: list[ConnectionDefPoint] = Field(default_factory=list, alias="connectionDefPoints")
    cross_section_mm2: float | None = None
    wire_length_m: float | None = None
    connection_type_localized: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "name",
        "identifying_name",
        "from_endpoint",
        "to_endpoint",
        "wire_number",
        "cross_section_raw",
        "wire_length_raw",
        "wire_color",
        "color_number",
        "potential",
        "signal_name",
        "connection_type",
        "cable",
        "cable_type",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _set_derived_fields(self) -> Self:
        self.cross_section_mm2 = _parse_unambiguous_cross_section(self.cross_section_raw)
        self.wire_length_m = _parse_float_text(self.wire_length_raw)
        self.connection_type_localized = _parse_localized_text(self.connection_type)
        return self

    def candidate_cable_names(self) -> list[str]:
        names: list[str] = []
        for candidate in (self.cable, self.from_endpoint, self.to_endpoint):
            if _is_placeholder_designator(candidate):
                continue
            if candidate not in names:
                names.append(candidate)
        return names

    def effective_wire_number(self) -> str | None:
        if self.wire_number:
            return self.wire_number
        for point in self.connection_def_points:
            if point.wire_number:
                return point.wire_number
        return None


class ConnectionsDocument(ExportModel):
    connection_count: int = Field(alias="connectionCount")
    connections: list[ConnectionRecord]

    @model_validator(mode="after")
    def _validate_count(self) -> Self:
        if self.connection_count != len(self.connections):
            raise ValueError(
                f"connectionCount={self.connection_count} does not match connections={len(self.connections)}"
            )
        return self

    def by_cable_name(self) -> dict[str, list[ConnectionRecord]]:
        grouped: dict[str, list[ConnectionRecord]] = defaultdict(list)
        for connection in self.connections:
            for candidate in connection.candidate_cable_names():
                grouped[candidate].append(connection)
        return dict(grouped)


class ConnectionResolution(ExportModel):
    connection_index: int
    candidate_cable_names: list[str] = Field(default_factory=list)
    effective_wire_number: str | None = None
    matched_cable_name: str | None = None
    matched_cable_function_names: list[str] = Field(default_factory=list)
    matched_wire_count: int = 0
    unresolved_reasons: list[str] = Field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return self.matched_cable_name is not None and self.matched_wire_count > 0


@dataclass(slots=True)
class EplanExportBundle:
    functions: FunctionsDocument
    cables: CablesDocument
    connections: ConnectionsDocument
    base_path: Path | None = None

    @classmethod
    def from_directory(cls, base_path: str | Path) -> Self:
        base_dir = Path(base_path)
        return cls(
            functions=load_functions_document(base_dir / "functions.json"),
            cables=load_cables_document(base_dir / "cables.json"),
            connections=load_connections_document(base_dir / "connections.json"),
            base_path=base_dir,
        )

    def _resolve_connection_with_indexes(
        self,
        connection: ConnectionRecord,
        connection_index: int,
        cable_index: dict[str, CableRecord],
        cable_function_index: dict[str, list[FunctionRecord]],
        wire_index: dict[tuple[str, str], list[CableWire]],
    ) -> ConnectionResolution:
        candidate_names = connection.candidate_cable_names()
        effective_wire_number = connection.effective_wire_number()
        matched_cable_name = next((name for name in candidate_names if name in cable_index), None)
        unresolved_reasons: list[str] = []

        if not candidate_names:
            unresolved_reasons.append("no_cable_candidate")
        if candidate_names and matched_cable_name is None:
            unresolved_reasons.append("cable_not_found")
        if effective_wire_number is None:
            unresolved_reasons.append("wire_number_missing")

        matched_cable_function_names: list[str] = []
        matched_wire_count = 0

        if matched_cable_name is not None:
            matched_cable_function_names = [
                function.name for function in cable_function_index.get(matched_cable_name, [])
            ]
            if not matched_cable_function_names:
                unresolved_reasons.append("cable_function_not_found")
            if effective_wire_number is not None:
                matched_wire_count = len(wire_index.get((matched_cable_name, effective_wire_number), []))
                if matched_wire_count == 0:
                    unresolved_reasons.append("wire_not_found")

        return ConnectionResolution(
            connection_index=connection_index,
            candidate_cable_names=candidate_names,
            effective_wire_number=effective_wire_number,
            matched_cable_name=matched_cable_name,
            matched_cable_function_names=matched_cable_function_names,
            matched_wire_count=matched_wire_count,
            unresolved_reasons=unresolved_reasons,
        )

    def resolve_connection(self, connection: ConnectionRecord, connection_index: int) -> ConnectionResolution:
        return self._resolve_connection_with_indexes(
            connection=connection,
            connection_index=connection_index,
            cable_index=self.cables.by_name(),
            cable_function_index=self.functions.cable_functions_by_name(),
            wire_index=self.cables.wire_index(),
        )

    def resolve_connections(self) -> list[ConnectionResolution]:
        cable_index = self.cables.by_name()
        cable_function_index = self.functions.cable_functions_by_name()
        wire_index = self.cables.wire_index()
        return [
            self._resolve_connection_with_indexes(
                connection=connection,
                connection_index=index,
                cable_index=cable_index,
                cable_function_index=cable_function_index,
                wire_index=wire_index,
            )
            for index, connection in enumerate(self.connections.connections)
        ]

    def orphan_cable_names(self) -> list[str]:
        cable_names = set(self.cables.by_name())
        cable_function_names = set(self.functions.cable_functions_by_name())
        return sorted(cable_names - cable_function_names)

    def unresolved_connection_count(self) -> int:
        return sum(1 for resolution in self.resolve_connections() if not resolution.is_resolved)


def load_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parse_json_text(raw_text: str) -> Any:
    return json.loads(raw_text.lstrip("\ufeff"))


def parse_functions_document(data: dict[str, Any]) -> FunctionsDocument:
    return FunctionsDocument.model_validate(data)


def parse_functions_document_text(raw_text: str) -> FunctionsDocument:
    return parse_functions_document(parse_json_text(raw_text))


def load_functions_document(path: str | Path) -> FunctionsDocument:
    return parse_functions_document(load_json_file(path))


def parse_cables_document(data: dict[str, Any]) -> CablesDocument:
    return CablesDocument.model_validate(data)


def parse_cables_document_text(raw_text: str) -> CablesDocument:
    return parse_cables_document(parse_json_text(raw_text))


def load_cables_document(path: str | Path) -> CablesDocument:
    return parse_cables_document(load_json_file(path))


def parse_connections_document(data: dict[str, Any]) -> ConnectionsDocument:
    return ConnectionsDocument.model_validate(data)


def parse_connections_document_text(raw_text: str) -> ConnectionsDocument:
    return parse_connections_document(parse_json_text(raw_text))


def load_connections_document(path: str | Path) -> ConnectionsDocument:
    return parse_connections_document(load_json_file(path))


def load_export_bundle(base_path: str | Path) -> EplanExportBundle:
    return EplanExportBundle.from_directory(base_path)