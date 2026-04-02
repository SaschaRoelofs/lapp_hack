"""
Machine Analyzer – Extracts a full machine graph from EPLAN-style PDF schematics.

Parses structured data sections (cover page, TOC, parts list, control overview,
cable overview, terminal diagrams) to build a component graph with subsystems.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber


# ---------------------------------------------------------------------------
# IEC 81346 component type prefixes
# ---------------------------------------------------------------------------

COMPONENT_TYPE_MAP = {
    "A": "assembly",       # Baugruppe / Steuerung
    "B": "sensor",         # Sensor / Messgerät
    "E": "heater",         # Heizung
    "F": "protection",     # Sicherung / Schutzschalter
    "K": "controller",     # Relais / Steuerung
    "M": "motor",          # Motor / Aktor / Ventil
    "Q": "switch",         # Schalter / Schütz
    "S": "switch",         # Befehlsgerät
    "T": "transformer",    # Trafo / Netzteil
    "U": "duct",           # Kabelkanal / Tragschiene
    "W": "cable",          # Kabel / Leitung
    "X": "terminal",       # Klemme / Stecker
}

COMPONENT_TYPE_LABELS = {
    "assembly": "Baugruppe",
    "sensor": "Sensor",
    "heater": "Heizung",
    "protection": "Schutzgerät",
    "controller": "Steuerung",
    "motor": "Motor / Aktor",
    "switch": "Schalter / Schütz",
    "transformer": "Netzteil / Trafo",
    "duct": "Kabelkanal",
    "cable": "Kabel",
    "terminal": "Klemme",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Component:
    id: str = ""                          # e.g. "+SS1-F201"
    designation: str = ""                 # Short name e.g. "F201"
    component_type: str = ""              # From COMPONENT_TYPE_MAP
    description_de: str = ""
    description_en: str = ""
    manufacturer: str = ""
    order_number: str = ""
    technical_specs: str = ""             # e.g. "3...12A"
    sap_number: str = ""
    location: str = ""                    # e.g. "+SS1", "+MR1"
    subsystem: str = ""                   # Assigned subsystem name
    page_ref: str = ""                    # e.g. "&EFS=MA1+SS1/12"
    quantity: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MachineConnection:
    cable_name: str = ""                  # e.g. "WM201"
    cable_type: str = ""                  # e.g. "ÖLFLEX 191"
    cable_spec: str = ""                  # e.g. "4G2,5 mm²"
    cross_section_mm2: Optional[float] = None
    num_cores: Optional[int] = None
    from_component: str = ""              # Component id
    to_component: str = ""                # Component id
    connection_type: str = ""             # "external_cable" or "internal_wiring"
    function_de: str = ""
    function_en: str = ""
    sap_number: str = ""
    length_m: Optional[float] = None
    page_ref: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Subsystem:
    name: str = ""
    name_en: str = ""
    page_ref: int = 0                     # Sheet number in PDF
    component_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TechnicalData:
    rated_voltage: str = ""
    frequency: str = ""
    control_voltage: str = ""
    connected_load: str = ""
    full_load_current: str = ""
    max_pre_fuse: str = ""
    enclosure_type: str = ""
    sccr: str = ""
    model: str = ""
    project: str = ""
    article_no: str = ""
    doc_no: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IOAssignment:
    controller_id: str = ""
    connector: str = ""                   # e.g. "DI1", "DO1", "AI2", "AO1"
    pin: str = ""                         # e.g. "1", "2"
    signal_type: str = ""                 # "DI", "DO", "AI", "AO", "RS485"
    function_de: str = ""
    function_en: str = ""
    target_component: str = ""
    page_ref: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MachineGraph:
    technical_data: TechnicalData = field(default_factory=TechnicalData)
    components: list[Component] = field(default_factory=list)
    connections: list[MachineConnection] = field(default_factory=list)
    subsystems: list[Subsystem] = field(default_factory=list)
    io_assignments: list[IOAssignment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pages_analyzed: int = 0

    def to_dict(self) -> dict:
        return {
            "technical_data": self.technical_data.to_dict(),
            "components": [c.to_dict() for c in self.components],
            "connections": [c.to_dict() for c in self.connections],
            "subsystems": [s.to_dict() for s in self.subsystems],
            "io_assignments": [io.to_dict() for io in self.io_assignments],
            "warnings": self.warnings,
            "pages_analyzed": self.pages_analyzed,
        }


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def _extract_texts(pdf_bytes: bytes) -> list[str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = [page.get_text() for page in doc]
    doc.close()
    return texts


def _extract_tables(pdf_bytes: bytes) -> list[list[list]]:
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    result = []
    for page in pdf.pages:
        result.append(page.extract_tables() or [])
    pdf.close()
    return result


# ---------------------------------------------------------------------------
# Phase 1: Page type detection for EPLAN documents
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Collapse whitespace/newlines to single spaces for robust keyword matching."""
    return re.sub(r"\s+", " ", text).lower().strip()


def _detect_page_type(text: str) -> str:
    """Detect EPLAN document section type from page text."""
    t = text.lower()
    # Normalized version with all whitespace collapsed — catches split keywords
    # like "Artikel\nstückliste" → "artikel stückliste"
    tn = _normalize_text(text)

    # Parts list — check BEFORE cover, because EPLAN footers contain
    # "Titel- / Deckblatt" text on every page including parts list pages
    if ("artikelstückliste" in tn or "artikel stückliste" in tn
            or "stückliste" in tn or "parts list" in tn):
        return "parts_list"

    # Cover page — only match if "titel" + "deckblatt" appear as a page TITLE
    # (header area), not just in the footer. Check that the title keywords
    # appear in the first ~500 chars of the page text.
    header_area = _normalize_text(text[:500])
    if ("deckblatt" in header_area and "titel" in header_area) or \
       ("title page" in header_area) or ("cover sheet" in header_area):
        return "cover"

    # Structure identifier overview
    if "strukturkennzeichen" in tn or "structure identifier" in tn:
        return "structure"

    # Table of contents
    if "inhaltsverzeichnis" in tn or "table of contents" in tn:
        return "toc"

    # Field device placement
    if ("feldgeräteplatzierung" in tn or "feldgeräte platzierung" in tn
            or "field device" in tn):
        return "field_devices"

    # Control overview — must check before generic circuit pages
    if ("steuerung übersicht" in tn or "steuerung  übersicht" in tn
            or "control overview" in tn):
        return "control_overview"

    # Cable overview
    if ("kabelübersicht" in tn or "kabel übersicht" in tn
            or "cable overview" in tn):
        return "cable_overview"

    # Terminal diagram
    if "klemmenplan" in tn or "terminal diagram" in tn:
        return "terminal_diagram"

    # Cable diagram
    if "kabelplan" in tn or "cable diagram" in tn:
        return "cable_diagram"

    # Cutting list
    if "zuschnittsliste" in tn or "cutting list" in tn:
        return "cutting_list"

    # Cabinet layout
    if ("schaltschrankaufbau" in tn or "schaltschrank aufbau" in tn
            or "control cabinet layout" in tn or "cabinet layout" in tn):
        return "cabinet_layout"

    # Circuit diagram pages (functional schematics)
    # These may or may not have the word "schaltplan" — check for keywords directly
    circuit_keywords = [
        "einspeisung", "power supply",
        "steuerspannung", "control voltage",
        "verteilung pe", "distribution pe",
        "phasenüberwachung", "phase monitoring",
        "schaltschrankheizung", "cabinet heating",
        "tankheizung", "tank heater",
        "heißgas", "hot gas",
        "nachspeisung", "feeding",
        "energiespar", "energy-saving",
        "leitfähigkeit", "conductivity",
        "motorklappe", "motor flap",
        "pumpe", "pump",
        "verdichter", "compressor",
        "kondensator", "condenser",
        "bedienpanel", "control panel",
        "steuerung ub", "control ub",
        "steuerung do", "control do",
        "steuerung di", "control di",
        "steuerung ai", "control ai",
        "steuerung ao", "control ao",
        "interface",
    ]
    if any(kw in tn for kw in circuit_keywords):
        return "circuit_page"

    return "other"


# ---------------------------------------------------------------------------
# Phase 1a: Cover page extraction
# ---------------------------------------------------------------------------

def _extract_cover_value(text: str, de_label: str, en_label: str, value_pattern: str = r"(.+)") -> str:
    """
    Extract a value from EPLAN cover page where labels appear in bilingual pairs:
        DE-Label
        EN-Label
        Value
    or sometimes:
        DE-Label\nEN-Label  Value
    """
    # Strategy 1: DE-label \n EN-label \n Value (each on separate lines)
    pattern1 = re.compile(
        re.escape(de_label) + r"\s*\n\s*" + re.escape(en_label) + r"\s*\n\s*" + value_pattern,
        re.IGNORECASE,
    )
    m = pattern1.search(text)
    if m:
        return m.group(1).strip()

    # Strategy 2: EN-label immediately followed by value on next line
    pattern2 = re.compile(
        re.escape(en_label) + r"\s*\n\s*" + value_pattern,
        re.IGNORECASE,
    )
    m = pattern2.search(text)
    if m:
        val = m.group(1).strip()
        # Skip if we grabbed another label (heuristic: doesn't start with a letter pair)
        if val and val != en_label and val != de_label:
            return val

    # Strategy 3: Value on same line after label
    pattern3 = re.compile(
        re.escape(en_label) + r"\s+" + value_pattern,
        re.IGNORECASE,
    )
    m = pattern3.search(text)
    if m:
        val = m.group(1).strip()
        if val and val != en_label:
            return val

    return ""


def _extract_cover_data(texts: list[str]) -> TechnicalData:
    """Extract technical data from cover page.

    EPLAN cover pages use a two-column layout for technical specs.  PyMuPDF
    linearises labels (left column) and values (right column) separately,
    so label → next-line → value matching does NOT work for the spec block.
    Instead we match values directly by their characteristic patterns.
    Metadata fields (Model, Project, Article no., Doc. no.) DO appear in
    label → value order in the title block, so those use label matching.
    """
    td = TechnicalData()
    for text in texts[:3]:  # Cover is usually in first 3 pages
        if _detect_page_type(text) not in ("cover", "other"):
            continue

        # ---- Technical specifications: match by value patterns ----
        if not td.rated_voltage:
            m = re.search(r"(\d+Y/\d+\s*V[^\n]*)", text)
            if m:
                td.rated_voltage = m.group(1).strip()

        if not td.frequency:
            m = re.search(r"(\d+\s*Hz)\b", text)
            if m:
                td.frequency = m.group(1).strip()

        if not td.control_voltage:
            # Match "24V DC" but not inside a longer string
            m = re.search(r"\b(\d+V\s*DC)\b", text)
            if m:
                td.control_voltage = m.group(1).strip()

        if not td.connected_load:
            m = re.search(r"(ca\.\s*\d+\s*kW)", text)
            if m:
                td.connected_load = m.group(1).strip()

        if not td.full_load_current:
            m = re.search(r"(ca\.\s*\d+\s*A)\b", text)
            if m:
                td.full_load_current = m.group(1).strip()

        if not td.max_pre_fuse:
            m = re.search(r"(Class\s+[A-Z],\s*\d+V\s*AC,\s*\d+\s*A)", text)
            if m:
                td.max_pre_fuse = m.group(1).strip()

        if not td.enclosure_type:
            m = re.search(r"\b(IP\s*\d+)\b", text)
            if m:
                td.enclosure_type = m.group(1).strip()

        if not td.sccr:
            m = re.search(r"SCCR\s*=?\s*(\d+\s*kA)", text)
            if m:
                td.sccr = m.group(1).strip()

        # ---- Metadata: DE + EN labels on same line, value on next line ----
        if not td.model:
            m = re.search(r"Modell\s+Model\s*\n\s*(.+)", text)
            if m:
                td.model = m.group(1).strip()

        if not td.project:
            m = re.search(r"Projekt\s+Project\s*\n\s*(.+)", text)
            if m:
                td.project = m.group(1).strip()

        if not td.article_no:
            # First occurrence of label may be followed by next label, not value.
            # Pick the first match whose captured value starts with a digit.
            for m in re.finditer(r"Artikelnr\.\s*Article\s*no\.\s*\n\s*(\S+)", text):
                val = m.group(1).strip()
                if val and val[0].isdigit():
                    td.article_no = val
                    break

        if not td.doc_no:
            m = re.search(r"Dok\.\s*Nr\.\s*Doc\.\s*no\.\s*\n\s*(\S+)", text)
            if m:
                td.doc_no = m.group(1).strip()

    return td


# ---------------------------------------------------------------------------
# Phase 1b: TOC extraction → Subsystems
# ---------------------------------------------------------------------------

def _extract_subsystems_from_toc(texts: list[str]) -> list[Subsystem]:
    """Extract functional subsystems from the table of contents pages."""
    subsystems = []
    seen = set()

    # Pattern: page description lines with sheet numbers from &EFS section
    # We look for lines like "Pumpe 1 (P1-2)" with a sheet number
    subsystem_pattern = re.compile(
        r"(?:^|\n)\s*(?:\+SS1\s+)?(\d+)\s+"
        r"([\w\s\-\(\)äöüÄÖÜß/]+?)\s*\n"
        r"\s*([\w\s\-\(\)]+)",
        re.MULTILINE,
    )

    # Simpler approach: look for known subsystem keywords in TOC pages
    KNOWN_SUBSYSTEMS = [
        ("Einspeisung", "Power supply"),
        ("Steuerspannung", "Control voltage"),
        ("Verteilung PE", "Distribution PE"),
        ("Phasenüberwachung", "Phase monitoring"),
        ("Schaltschrankheizung", "Control cabinet heating"),
        ("Tankheizung", "Tank heater"),
        ("Heißgas Bypass", "Hot gas bypass"),
        ("Automatische Nachspeisung", "Automatic feeding"),
        ("Energiesparsystem", "Energy-saving system"),
        ("Leitfähigkeit", "Conductivity"),
        ("Motorklappe", "Motor flap"),
        ("Pumpe 1", "Pump 1"),
        ("Pumpe 2", "Pump 2"),
        ("Verdichter", "Compressor"),
        ("Kondensatorlüfter", "Condenser fan"),
        ("Bedienpanel", "Control panel"),
        ("Steuerung Ub", "Control Ub"),
        ("Steuerung DO", "Control DO"),
        ("Steuerung AI", "Control AI"),
        ("Steuerung AO", "Control AO"),
        ("Interface", "Interface"),
        ("Steuerung Übersicht", "Control overview"),
    ]

    for i, text in enumerate(texts):
        ptype = _detect_page_type(text)
        # Search TOC pages, but also structure pages and first ~10 pages
        if ptype not in ("toc", "structure") and i >= 10:
            continue

        tn = _normalize_text(text)

        for name_de, name_en in KNOWN_SUBSYSTEMS:
            if name_de.lower() in tn and name_de not in seen:
                # Try to find sheet number near the subsystem name
                sheet_match = re.search(
                    re.escape(name_de) + r".*?(\d+)",
                    text,
                    re.IGNORECASE | re.DOTALL,
                )
                sheet = int(sheet_match.group(1)) if sheet_match else 0

                subsystems.append(Subsystem(
                    name=name_de,
                    name_en=name_en,
                    page_ref=sheet,
                ))
                seen.add(name_de)

    return subsystems


# ---------------------------------------------------------------------------
# Phase 1c: Parts list extraction → Components
# ---------------------------------------------------------------------------

def _extract_components_from_parts_list(
    texts: list[str],
    all_tables: list[list[list]],
) -> list[Component]:
    """Extract components from Artikelstückliste / Parts list pages."""
    components = []
    seen_ids = set()

    for page_idx, text in enumerate(texts):
        if _detect_page_type(text) != "parts_list":
            continue

        tables = all_tables[page_idx] if page_idx < len(all_tables) else []
        for table in tables:
            if len(table) < 2:
                continue

            header = table[0]
            if not header:
                continue
            # Normalize header: join multi-line cells, strip, lowercase
            header_lower = [
                _normalize_text(str(h)) if h else ""
                for h in header
            ]

            # Find column indices with expanded keyword matching
            col = {}
            for ci, h in enumerate(header_lower):
                if any(k in h for k in [
                    "betriebsmittel", "device tag", "bmk", "kennung",
                    "betriebsmittelkennzeichnung",
                ]):
                    col["tag"] = ci
                elif any(k in h for k in ["sap nummer", "sap number", "sap-nr", "sap nr"]):
                    col["sap"] = ci
                elif any(k in h for k in ["menge", "quantity", "stk", "anzahl"]):
                    col["qty"] = ci
                elif any(k in h for k in ["bezeichnung", "designation", "beschreibung", "description"]):
                    col["desc"] = ci
                elif any(k in h for k in [
                    "technische", "technical", "nenndaten", "rated data",
                ]):
                    col["specs"] = ci
                elif any(k in h for k in [
                    "bestellnummer", "order number", "bestell-nr", "bestell nr",
                    "order no",
                ]):
                    col["order"] = ci
                elif any(k in h for k in ["hersteller", "manufacturer", "lieferant"]):
                    col["mfr"] = ci
                elif any(k in h for k in ["platzierung", "placement", "einbauort"]):
                    col["place"] = ci
                elif "ul" in h or "csa" in h:
                    col["ul"] = ci

            # Fallback: if no tag column found in header, detect by cell content
            if "tag" not in col:
                tag_pattern = re.compile(r"\+\w+-[A-Z]\w+")
                for ci in range(len(header)):
                    matches = 0
                    for row in table[1:min(6, len(table))]:
                        if row and ci < len(row):
                            cell = str(row[ci] or "").strip()
                            if tag_pattern.search(cell):
                                matches += 1
                    if matches >= 2:
                        col["tag"] = ci
                        break

            if "tag" not in col:
                continue

            for row in table[1:]:
                if not row or len(row) <= col["tag"]:
                    continue

                tag_raw = str(row[col["tag"]] or "").strip()
                if not tag_raw:
                    continue

                # Parse device tag: e.g. "+SS1-F201\n&EFS=MA1+SS1/12"
                lines = tag_raw.split("\n")
                tag = lines[0].strip()
                page_ref = lines[1].strip() if len(lines) > 1 else ""

                # Skip terminal strips (X*), cable ducts (U*), mounting rails
                designation = tag.split("-")[-1] if "-" in tag else tag
                prefix = re.match(r"([A-Z])", designation)
                if not prefix:
                    continue

                comp_type = COMPONENT_TYPE_MAP.get(prefix.group(1), "")
                # Skip ducts and pure terminal strips from visual representation
                if comp_type in ("duct", "terminal"):
                    continue

                # Build full component id
                comp_id = tag

                if comp_id in seen_ids:
                    continue
                seen_ids.add(comp_id)

                # Extract location from tag
                location = ""
                loc_match = re.match(r"(\+\w+)", tag)
                if loc_match:
                    location = loc_match.group(1)

                def _cell(key):
                    if key in col and col[key] < len(row):
                        val = str(row[col[key]] or "").strip()
                        return val.split("\n")[0].strip() if val else ""
                    return ""

                desc_raw = _cell("desc")
                desc_lines = str(row[col["desc"]] or "").strip().split("\n") if "desc" in col and col["desc"] < len(row) else [""]

                comp = Component(
                    id=comp_id,
                    designation=designation,
                    component_type=comp_type,
                    description_de=desc_lines[0].strip() if desc_lines else "",
                    description_en=desc_lines[1].strip() if len(desc_lines) > 1 else "",
                    manufacturer=_cell("mfr"),
                    order_number=_cell("order"),
                    technical_specs=_cell("specs"),
                    sap_number=_cell("sap"),
                    location=location,
                    page_ref=page_ref,
                    quantity=_safe_int_val(_cell("qty")) or 1,
                )
                components.append(comp)

    return components


def _safe_int_val(s: str) -> Optional[int]:
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Phase 1d: Field device placement extraction
# ---------------------------------------------------------------------------

def _extract_field_devices(texts: list[str], all_tables: list[list[list]]) -> list[Component]:
    """Extract field device list for components located in machine room (+MR1)."""
    components = []
    seen = set()

    for page_idx, text in enumerate(texts):
        ptype = _detect_page_type(text)

        # Primary: dedicated field device pages
        if ptype == "field_devices":
            tables = all_tables[page_idx] if page_idx < len(all_tables) else []
            for table in tables:
                if len(table) < 2:
                    continue

                # Detect tag and placement columns from header
                header = table[0] if table else []
                tag_col = 0
                place_col = 1
                if header:
                    for ci, h in enumerate(header or []):
                        hn = _normalize_text(str(h or ""))
                        if "betriebsmittel" in hn or "device tag" in hn:
                            tag_col = ci
                        elif "platzierung" in hn or "placement" in hn:
                            place_col = ci

                for row in table[1:]:
                    if not row:
                        continue
                    tag_str = str(row[tag_col] or "").strip() if tag_col < len(row) else ""
                    place_str = str(row[place_col] or "").strip() if place_col < len(row) else ""
                    if not tag_str:
                        continue
                    m = re.match(r"(\+\w+-([A-Z]\w+))", tag_str)
                    if m and m.group(1) not in seen:
                        tag = m.group(1)
                        desig = m.group(2)
                        prefix = re.match(r"([A-Z])", desig)
                        comp_type = COMPONENT_TYPE_MAP.get(prefix.group(1), "") if prefix else ""
                        if comp_type in ("duct", "terminal"):
                            continue
                        seen.add(tag)
                        loc_match = re.match(r"(\+\w+)", tag)
                        location = loc_match.group(1) if loc_match else ""
                        components.append(Component(
                            id=tag,
                            designation=desig,
                            component_type=comp_type,
                            location=location,
                            page_ref=place_str,
                        ))

        # Secondary: scan ALL circuit/schematic pages for +MR1-Xnnn patterns in text
        # This catches field devices drawn on circuit diagrams
        if ptype in ("circuit_page", "cable_overview", "cable_diagram", "terminal_diagram", "other"):
            for m in re.finditer(r"(\+MR1-([A-Z]\d{1,4}))\b", text):
                tag = m.group(1)
                desig = m.group(2)
                if tag in seen:
                    continue
                prefix = desig[0]
                comp_type = COMPONENT_TYPE_MAP.get(prefix, "")
                if not comp_type or comp_type in ("duct", "terminal"):
                    continue
                seen.add(tag)
                components.append(Component(
                    id=tag,
                    designation=desig,
                    component_type=comp_type,
                    location="+MR1",
                ))

    return components


# ---------------------------------------------------------------------------
# Phase 1e: Cable overview extraction → Connections
# ---------------------------------------------------------------------------

def _extract_cable_overview(
    texts: list[str],
    all_tables: list[list[list]],
) -> list[MachineConnection]:
    """Extract cable list from Kabelübersicht / Cable overview."""
    connections = []

    for page_idx, text in enumerate(texts):
        if _detect_page_type(text) != "cable_overview":
            continue

        tables = all_tables[page_idx] if page_idx < len(all_tables) else []
        for table in tables:
            if len(table) < 2:
                continue

            header = table[0]
            if not header:
                continue
            # Normalize header: collapse multi-line cells
            header_lower = [
                _normalize_text(str(h)) if h else ""
                for h in header
            ]

            col = {}
            for ci, h in enumerate(header_lower):
                if any(k in h for k in [
                    "kabelname", "cable name", "kabel name", "kabel-name",
                ]):
                    col["name"] = ci
                elif any(k in h for k in [
                    "platzierung", "placement", "einbauort",
                ]):
                    col["place"] = ci
                elif any(k in h for k in ["sap", "nummer", "number"]):
                    col["sap"] = ci
                elif any(k in h for k in ["funktion", "function"]):
                    col["func"] = ci
                elif any(k in h for k in ["hersteller", "manufacturer"]):
                    col["mfr"] = ci
                elif any(k in h for k in [
                    "bestellnummer", "order number", "bestell-nr", "order no",
                ]):
                    col["order"] = ci
                elif any(k in h for k in [
                    "leitungstyp", "cable type", "kabeltyp", "leitung",
                ]):
                    col["type"] = ci
                elif any(k in h for k in ["länge", "length", "laenge"]):
                    col["length"] = ci

            # Fallback: detect cable name column by cell content pattern
            if "name" not in col:
                cable_pattern = re.compile(r"\+\w+-W[A-Z]\w+")
                for ci in range(len(header)):
                    matches = 0
                    for row in table[1:min(6, len(table))]:
                        if row and ci < len(row):
                            cell = str(row[ci] or "").strip()
                            if cable_pattern.search(cell):
                                matches += 1
                    if matches >= 2:
                        col["name"] = ci
                        break

            if "name" not in col:
                continue

            for row in table[1:]:
                if not row or len(row) <= col["name"]:
                    continue

                name_raw = str(row[col["name"]] or "").strip()
                if not name_raw:
                    continue

                def _cell(key):
                    if key in col and col[key] < len(row):
                        return str(row[col[key]] or "").strip()
                    return ""

                cable_type_raw = _cell("type")
                # Parse cable type and spec: "ÖLFLEX 191\n4G2,5 mm²"
                type_lines = cable_type_raw.split("\n")
                cable_type = type_lines[0].strip() if type_lines else ""
                cable_spec = type_lines[1].strip() if len(type_lines) > 1 else ""

                # Parse cross-section and cores from spec
                cs = None
                cores = None
                # Try from cable_spec first, then from cable_type_raw as a whole
                spec_text = cable_spec or cable_type_raw
                spec_match = re.search(r"(\d+)\s*[xXGg]\s*(\d+[,.]?\d*)", spec_text)
                if spec_match:
                    cores = int(spec_match.group(1))
                    cs = float(spec_match.group(2).replace(",", "."))

                func_raw = _cell("func")
                func_lines = func_raw.split("\n")

                length_raw = _cell("length")
                length = None
                if length_raw:
                    lm = re.search(r"(\d+[,.]?\d*)", length_raw.replace(",", "."))
                    if lm:
                        length = float(lm.group(1))

                conn = MachineConnection(
                    cable_name=name_raw,
                    cable_type=cable_type,
                    cable_spec=cable_spec,
                    cross_section_mm2=cs,
                    num_cores=cores,
                    function_de=func_lines[0].strip() if func_lines else "",
                    function_en=func_lines[1].strip() if len(func_lines) > 1 else "",
                    sap_number=_cell("sap"),
                    length_m=length,
                    page_ref=_cell("place"),
                )
                connections.append(conn)

    return connections


# ---------------------------------------------------------------------------
# Phase 1f: Control overview extraction → I/O assignments
# ---------------------------------------------------------------------------

# Pin type keywords used in EPLAN control overview pages
_PIN_TYPES = {
    "NO", "COM", "NC", "DI", "GND", "AI(I)", "AI(R)", "AO(U)", "L+",
    "Modbus_A", "Modbus_B", "Modbus_GND", "+24VDC", "+24V", "n.c.",
}

# Connector names used on K801 controller
_CONNECTOR_PATTERN = re.compile(
    r"^(DI[1-6]|DO[1-5]|ES\d|AI[1-3]|AO[1-2]|AIO[1-2]|IFP\s*(?:AI|DO)\d|"
    r"RS-485-[23]|CON\d+)$"
)


def _parse_control_overview_text(
    text: str,
    assignments: list,
    seen: set,
):
    """
    Parse the structured text of EPLAN Control Overview pages (Steuerung Übersicht).

    The text layout on these pages follows a pattern like:
        <pin_number>\n<PIN_TYPE> <function_de>\n<function_en>\n/<page.col>\n<CONNECTOR>
    or:
        <pin_number>\n<PIN_TYPE> /<page.col>

    We parse line-by-line, tracking the current connector context.
    """
    lines = text.split("\n")
    current_connector = ""

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detect connector headers (DI1, DO1, ES1, AI2, AO1, AIO1, etc.)
        if _CONNECTOR_PATTERN.match(line):
            current_connector = line.replace(" ", "")
            i += 1
            continue

        # Look for pin number lines: a line that is just a number 1-10
        if line.isdigit() and 1 <= int(line) <= 20:
            pin = line
            # Next line should be PIN_TYPE + optional function
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()

                # Check if next line starts with a pin type
                pin_type = ""
                func_part = ""
                for pt in sorted(_PIN_TYPES, key=len, reverse=True):
                    if next_line.startswith(pt):
                        pin_type = pt
                        func_part = next_line[len(pt):].strip()
                        break

                if pin_type:
                    func_de = ""
                    func_en = ""
                    page_ref = ""

                    # func_part may contain function + page_ref on same line
                    # e.g. "Pumpe 1" or "/12.8" or "Pumpe 1\nPump 1"
                    pr_match = re.search(r"/(\d+\.\d+)", func_part)
                    if pr_match:
                        page_ref = "/" + pr_match.group(1)
                        func_de = func_part[:pr_match.start()].strip()
                    else:
                        func_de = func_part

                    # Look at subsequent lines for function_en, page_ref, or connector
                    j = i + 2
                    while j < min(i + 5, len(lines)):
                        subsequent = lines[j].strip()
                        if not subsequent:
                            j += 1
                            continue
                        if _CONNECTOR_PATTERN.match(subsequent):
                            current_connector = subsequent.replace(" ", "")
                            j += 1
                            break
                        if subsequent.isdigit():
                            break  # next pin
                        # Check for pin type (start of next entry)
                        is_pin_type = any(subsequent.startswith(pt) for pt in _PIN_TYPES)
                        if is_pin_type:
                            break
                        pr = re.search(r"/(\d+\.\d+)", subsequent)
                        if pr:
                            if not page_ref:
                                page_ref = "/" + pr.group(1)
                            j += 1
                            continue
                        if not func_de:
                            func_de = subsequent
                        elif not func_en and func_de:
                            # Second text line = English translation
                            func_en = subsequent
                        j += 1

                    # Determine signal type from connector or pin_type
                    sig_type = ""
                    if current_connector:
                        for prefix in ("DI", "DO", "AI", "AO", "ES", "IFP"):
                            if current_connector.startswith(prefix):
                                sig_type = prefix if prefix in ("DI", "DO", "AI", "AO") else "DO"
                                break
                        if "RS-485" in current_connector:
                            sig_type = "RS485"
                        elif "CON" in current_connector:
                            sig_type = "PWR"

                    if func_de:
                        key = (pin, func_de)
                        if key not in seen:
                            seen.add(key)
                            assignments.append(IOAssignment(
                                controller_id="K801",
                                connector=current_connector,
                                pin=pin,
                                signal_type=sig_type,
                                function_de=func_de,
                                function_en=func_en,
                                page_ref=page_ref,
                            ))

        i += 1


def _extract_control_overview(
    texts: list[str],
    all_tables: list[list[list]],
) -> list[IOAssignment]:
    """Extract I/O assignments from Steuerung Übersicht / Control overview pages."""
    assignments = []
    seen = set()

    for page_idx, text in enumerate(texts):
        ptype = _detect_page_type(text)
        # Accept both control_overview and circuit pages that are control-related
        if ptype != "control_overview" and not (
            ptype == "circuit_page" and any(
                kw in text.lower() for kw in [
                    "steuerung do", "steuerung di", "steuerung ai",
                    "steuerung ao", "steuerung ub", "control do",
                    "control di", "control ai", "control ao", "control ub",
                ]
            )
        ):
            continue

        # Determine signal type from page content
        tn = _normalize_text(text)
        page_signal = ""
        if "steuerung do" in tn or "control do" in tn:
            page_signal = "DO"
        elif "steuerung di" in tn or "control di" in tn:
            page_signal = "DI"
        elif "steuerung ai" in tn or "control ai" in tn:
            page_signal = "AI"
        elif "steuerung ao" in tn or "control ao" in tn:
            page_signal = "AO"
        elif "steuerung ub" in tn or "control ub" in tn:
            page_signal = "Ub"

        # Strategy 1: Try pdfplumber tables
        tables = all_tables[page_idx] if page_idx < len(all_tables) else []
        for table in tables:
            if len(table) < 2:
                continue
            for row in table[1:]:
                if not row or len(row) < 2:
                    continue

                # Look for rows with a pin number and a function description
                # Typical: [pin, type, function_de, function_en, page_ref]
                for ci, cell in enumerate(row):
                    cell_str = str(cell or "").strip()
                    # Find a cell that looks like a pin type (NO, COM, NC, DI, GND, AI, AO, L+)
                    if cell_str in ("NO", "COM", "NC", "DI", "GND", "AI(I)", "AI(R)", "AO(U)", "L+",
                                    "Modbus_A", "Modbus_B"):
                        # Pin number is typically in a previous cell
                        pin = ""
                        for pi in range(ci - 1, -1, -1):
                            p = str(row[pi] or "").strip()
                            if p.isdigit():
                                pin = p
                                break

                        # Function is typically in the next cell(s)
                        func_de = ""
                        func_en = ""
                        page_ref = ""
                        for fi in range(ci + 1, min(ci + 4, len(row))):
                            val = str(row[fi] or "").strip()
                            if not val:
                                continue
                            if re.match(r"^/\d+\.\d+$", val):
                                page_ref = val
                            elif not func_de:
                                lines = val.split("\n")
                                func_de = lines[0].strip()
                                func_en = lines[1].strip() if len(lines) > 1 else ""
                            elif not page_ref and re.search(r"/\d+\.\d+", val):
                                page_ref = val.strip()

                        key = (pin, func_de)
                        if pin and func_de and key not in seen:
                            seen.add(key)
                            assignments.append(IOAssignment(
                                controller_id="K801",
                                pin=pin,
                                signal_type=page_signal or cell_str,
                                function_de=func_de,
                                function_en=func_en,
                                page_ref=page_ref,
                            ))

        # Strategy 2: Regex fallback on raw text
        # Pattern: pin_number  TYPE  function  /page.col
        io_patterns = re.findall(
            r"(\d+)\s+(?:NO|COM|NC|DI|GND|AI\((?:I|R)\)|AO\(U\)|L\+|Modbus_\w+)\s+"
            r"([\w\s\-\(\)äöüÄÖÜß/]+?)\s*"
            r"(?:/(\d+\.\d+))",
            text,
        )

        for pin, func, page_ref in io_patterns:
            func_clean = func.strip()
            if not func_clean or func_clean in ("", "/"):
                continue

            key = (pin, func_clean)
            if key in seen:
                continue
            seen.add(key)

            # Split bilingual function if present
            func_lines = func_clean.split("\n")
            func_de = func_lines[0].strip()
            func_en = func_lines[1].strip() if len(func_lines) > 1 else ""

            sig_type = page_signal
            if not sig_type:
                # Determine from nearby context
                context_start = max(0, text.find(func_clean) - 50)
                context_end = text.find(func_clean) + 50
                ctx = text[context_start:context_end]
                for st in ("DI", "DO", "AI", "AO"):
                    if re.search(rf"\b{st}\d*\b", ctx):
                        sig_type = st
                        break

            assignments.append(IOAssignment(
                controller_id="K801",
                pin=pin,
                signal_type=sig_type,
                function_de=func_de,
                function_en=func_en,
                page_ref=f"/{page_ref}" if page_ref else "",
            ))

        # Strategy 3: Structured text parsing for Control Overview pages
        # These pages have connector blocks like:
        #   1\nNO Pumpe 1\nPump 1\n/12.8\nDO1\n2\nCOM /12.8
        # Parse connector headers and pin entries from the text structure
        _parse_control_overview_text(text, assignments, seen)

    return assignments


# ---------------------------------------------------------------------------
# Phase 1g: Circuit page scanning for subsystem→component mapping
# ---------------------------------------------------------------------------

# Maps page title keywords to subsystem names
PAGE_TITLE_TO_SUBSYSTEM = {
    "einspeisung": "Einspeisung",
    "power supply": "Einspeisung",
    "steuerspannung": "Steuerspannung",
    "control voltage": "Steuerspannung",
    "verteilung pe": "Verteilung PE",
    "distribution pe": "Verteilung PE",
    "phasenüberwachung": "Phasenüberwachung",
    "phase monitoring": "Phasenüberwachung",
    "schaltschrankheizung": "Schaltschrankheizung",
    "cabinet heating": "Schaltschrankheizung",
    "tankheizung": "Tankheizung",
    "tank heater": "Tankheizung",
    "heißgas": "Heißgas Bypass",
    "hot gas": "Heißgas Bypass",
    "nachspeisung": "Automatische Nachspeisung",
    "automatic feeding": "Automatische Nachspeisung",
    "energiespar": "Energiesparsystem",
    "energy-saving": "Energiesparsystem",
    "leitfähigkeit": "Leitfähigkeit",
    "conductivity": "Leitfähigkeit",
    "motorklappe": "Motorklappe",
    "motor flap": "Motorklappe",
    "pumpe 1": "Pumpe 1",
    "pump 1": "Pumpe 1",
    "pumpe 2": "Pumpe 2",
    "pump 2": "Pumpe 2",
    "verdichter": "Verdichter",
    "compressor": "Verdichter",
    "kondensatorlüfter": "Kondensatorlüfter",
    "condenser fan": "Kondensatorlüfter",
    "bedienpanel": "Bedienpanel",
    "control panel": "Bedienpanel",
    "steuerung ub": "Steuerung Ub",
    "control ub": "Steuerung Ub",
    "steuerung do": "Steuerung DO",
    "control do": "Steuerung DO",
    "steuerung ai": "Steuerung AI",
    "control ai": "Steuerung AI",
    "steuerung ao": "Steuerung AO",
    "control ao": "Steuerung AO",
    "interface": "Interface",
    "steuerung übersicht": "Steuerung Übersicht",
    "control overview": "Steuerung Übersicht",
}


def _build_sheet_to_subsystem_map(texts: list[str]) -> dict[int, str]:
    """Build mapping from &EFS circuit diagram sheet number to subsystem name.

    Circuit diagram pages (=MA1+SS1) are in the &EFS section and numbered
    sequentially starting from 1.  Each page's subsystem is identified from
    its title keywords using PAGE_TITLE_TO_SUBSYSTEM.
    """
    sheet_map: dict[int, str] = {}
    sheet_num = 0

    for text in texts:
        ptype = _detect_page_type(text)
        if ptype not in ("circuit_page", "control_overview"):
            continue

        # Only count pages in the &EFS section (must reference =MA1 or +SS1)
        tn = _normalize_text(text[:500])
        if "=ma1" not in tn and "+ss1" not in tn:
            continue

        sheet_num += 1

        # Find subsystem name from page title keywords
        for keyword, sub_name in PAGE_TITLE_TO_SUBSYSTEM.items():
            if keyword in tn:
                sheet_map[sheet_num] = sub_name
                break

    return sheet_map


def _scan_circuit_pages_for_components(texts: list[str]) -> dict[str, list[str]]:
    """
    Scan circuit diagram pages to find which components appear on which page,
    mapping them to subsystems by page title.

    Returns: {subsystem_name: [component_designation, ...]}

    Uses specificity scoring: a component is assigned to the subsystem whose
    page has the fewest total component references (most specific page).
    E.g. "Pumpe 1" page mentions only F201, M201, B201
    while "Einspeisung" mentions Q1, Q151, Q152, F21, ... (many cross-refs).
    So F201 should be assigned to "Pumpe 1", not "Einspeisung".
    """
    # First pass: collect all component refs per subsystem, with page sizes
    subsystem_components: dict[str, list[str]] = {}
    subsystem_page_size: dict[str, int] = {}  # total comp refs on that page

    for page_idx, text in enumerate(texts):
        # Detect subsystem from page title — use normalized text for robustness
        tn = _normalize_text(text)
        subsystem = None
        for keyword, sub_name in PAGE_TITLE_TO_SUBSYSTEM.items():
            if keyword in tn:
                subsystem = sub_name
                break

        if not subsystem:
            continue

        # Find component designations on this page
        # Pattern: letter + 2-4 digits (like F201, M151, Q151, K801, B451)
        # Require at least 2 digits to avoid false positives from terminal refs
        # like T1, T2, T3 (motor terminals "2/T1"), M63 (cable gland), S0 (Siemens size)
        # Also exclude digits that are part of larger alphanumeric strings (e.g. "F803" in order numbers)
        comp_refs = set()

        # Only match standalone designations: preceded by whitespace/line-start/dash, not by alphanumeric
        for m in re.finditer(r"(?:^|[\s\-\+/])([A-Z]\d{2,4})\b", text):
            desig = m.group(1)
            prefix = desig[0]
            if prefix in COMPONENT_TYPE_MAP and COMPONENT_TYPE_MAP[prefix] not in ("duct", "terminal"):
                comp_refs.add(desig)

        # Also look for full component tags with location: +MR1-B201, +SS1-F201
        for m in re.finditer(r"(\+\w+)-([A-Z]\d{1,4})\b", text):
            desig = m.group(2)
            prefix = desig[0]
            if prefix in COMPONENT_TYPE_MAP and COMPONENT_TYPE_MAP[prefix] not in ("duct", "terminal"):
                comp_refs.add(desig)

        if comp_refs:
            subsystem_components.setdefault(subsystem, [])
            for ref in comp_refs:
                if ref not in subsystem_components[subsystem]:
                    subsystem_components[subsystem].append(ref)
            # Track page size — use the smallest page for this subsystem
            if subsystem not in subsystem_page_size or len(comp_refs) < subsystem_page_size[subsystem]:
                subsystem_page_size[subsystem] = len(comp_refs)

    return subsystem_components


def _create_fallback_components(
    existing_components: list[Component],
    subsystem_comp_map: dict[str, list[str]],
    connections: list[MachineConnection],
    texts: list[str],
) -> list[Component]:
    """
    Create basic Component objects for designations found on circuit pages or
    cable connections that were NOT found by parts_list or field_devices parsers.

    This recovers field devices (sensors, motors, heaters in +MR1) that are
    drawn on schematic pages but may not appear in the parts list table.
    """
    existing_desigs = {c.designation for c in existing_components}
    new_components = []
    seen = set()

    # Collect all component locations from text: "+MR1-B201" → B201 is in +MR1
    location_map: dict[str, str] = {}
    for text in texts:
        for m in re.finditer(r"(\+\w+)-([A-Z]\d{2,4})\b", text):
            loc = m.group(1)
            desig = m.group(2)
            # Prefer +MR1 (field) over +SS1 (cabinet) if both appear
            if desig not in location_map or loc == "+MR1":
                location_map[desig] = loc

    # Source 1: component designations from circuit pages
    for sub_name, desig_list in subsystem_comp_map.items():
        for desig in desig_list:
            if desig in existing_desigs or desig in seen:
                continue

            prefix = desig[0]
            comp_type = COMPONENT_TYPE_MAP.get(prefix, "")
            if not comp_type or comp_type in ("duct", "terminal"):
                continue

            # Only accept bare designations that also appear in full-tag
            # format (+LOC-DESIG) somewhere in the document.  This filters
            # false positives like M63 (metric thread), S00 (contactor size),
            # F803 (order-number fragment).
            if desig not in location_map:
                continue

            location = location_map.get(desig, "")
            comp_id = f"{location}-{desig}" if location else desig

            new_components.append(Component(
                id=comp_id,
                designation=desig,
                component_type=comp_type,
                location=location,
                subsystem=sub_name,
            ))
            seen.add(desig)

    # Source 2: component designations from cable connections (to_component references)
    for conn in connections:
        name = conn.cable_name
        # Extract target designation from cable name: "+MR1-WM201" → M201
        parts = name.split("-")
        for p in parts:
            if p.startswith("W") and len(p) > 1 and p[1].isalpha():
                target_desig = p[1:]
                target_desig = re.sub(r"-\d+$", "", target_desig)
                break
        else:
            continue

        if target_desig in existing_desigs or target_desig in seen:
            continue

        prefix = target_desig[0]
        comp_type = COMPONENT_TYPE_MAP.get(prefix, "")
        if not comp_type or comp_type in ("duct", "terminal"):
            continue

        location = location_map.get(target_desig, "")
        # Field devices referenced by cables are typically in +MR1
        if not location and comp_type in ("motor", "sensor", "heater"):
            location = "+MR1"
        comp_id = f"{location}-{target_desig}" if location else target_desig

        new_components.append(Component(
            id=comp_id,
            designation=target_desig,
            component_type=comp_type,
            location=location,
        ))
        seen.add(target_desig)

    return new_components


# ---------------------------------------------------------------------------
# Phase 2a: Infer internal wiring from IEC 81346 patterns
# ---------------------------------------------------------------------------

def _infer_internal_connections(
    components: list[Component],
    subsystem_comp_map: dict[str, list[str]],
) -> list[MachineConnection]:
    """
    Infer cabinet-internal wiring connections based on IEC 81346 component
    type patterns and subsystem co-occurrence.

    Standard patterns:
    - F (fuse/breaker) → Q (contactor) → motor/heater in same subsystem
    - F (fuse/breaker) → T (transformer) in same subsystem
    - F (fuse/breaker) → K (controller) direct feed
    - B (sensor) → K801 (main controller) signal line
    - S (switch) → K801 (main controller) signal line
    - A (assembly/panel) → K801 (main controller)
    """
    connections = []
    comp_by_desig = {c.designation: c for c in components}

    # Group components by subsystem
    sub_components: dict[str, list[Component]] = {}
    for comp in components:
        if comp.subsystem:
            sub_components.setdefault(comp.subsystem, []).append(comp)

    # Also use the subsystem_comp_map for components that may not have subsystem set yet
    for sub_name, desig_list in subsystem_comp_map.items():
        if sub_name not in sub_components:
            sub_components[sub_name] = []
        for d in desig_list:
            if d in comp_by_desig:
                c = comp_by_desig[d]
                if c not in sub_components[sub_name]:
                    sub_components[sub_name].append(c)

    seen_pairs = set()

    def _add(from_id: str, to_id: str, func_de: str, func_en: str):
        pair = (from_id, to_id)
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        connections.append(MachineConnection(
            cable_name=f"INT_{from_id.split('-')[-1]}_{to_id.split('-')[-1]}",
            connection_type="internal_wiring",
            from_component=from_id,
            to_component=to_id,
            function_de=func_de,
            function_en=func_en,
        ))

    for sub_name, comps in sub_components.items():
        # Classify components in this subsystem by type
        fuses = [c for c in comps if c.component_type == "protection"]
        contactors = [c for c in comps if c.component_type == "switch" and c.designation.startswith("Q") and c.designation != "Q1"]
        motors = [c for c in comps if c.component_type == "motor"]
        transformers = [c for c in comps if c.component_type == "transformer"]
        heaters = [c for c in comps if c.component_type == "heating"]
        sensors = [c for c in comps if c.component_type == "sensor"]
        controllers = [c for c in comps if c.component_type in ("controller", "assembly")]
        switches = [c for c in comps if c.component_type == "switch" and c.designation.startswith("S")]

        # Pattern: F → Q → M (motor protection chain)
        for f in fuses:
            f_num = re.search(r"\d+", f.designation)
            if not f_num:
                continue
            num = f_num.group()

            # Find matching contactor Q with same number
            q_match = next((q for q in contactors if re.search(r"\d+", q.designation) and re.search(r"\d+", q.designation).group() == num), None)
            if q_match:
                _add(f.id, q_match.id, f"Schutz {f.designation}→{q_match.designation}", f"Protection {f.designation}→{q_match.designation}")
                # Q → M (if motor with same number exists)
                m_match = next((m for m in motors if re.search(r"\d+", m.designation) and re.search(r"\d+", m.designation).group() == num), None)
                if m_match:
                    _add(q_match.id, m_match.id, f"Leistung {q_match.designation}→{m_match.designation}", f"Power {q_match.designation}→{m_match.designation}")
            else:
                # F → M directly (no contactor)
                m_match = next((m for m in motors if re.search(r"\d+", m.designation) and re.search(r"\d+", m.designation).group() == num), None)
                if m_match:
                    _add(f.id, m_match.id, f"Schutz {f.designation}→{m_match.designation}", f"Protection {f.designation}→{m_match.designation}")

            # F → T (transformer with same number)
            t_match = next((t for t in transformers if re.search(r"\d+", t.designation) and re.search(r"\d+", t.designation).group() == num), None)
            if t_match:
                _add(f.id, t_match.id, f"Schutz {f.designation}→{t_match.designation}", f"Protection {f.designation}→{t_match.designation}")

            # F → E (heater with same number)
            e_match = next((e for e in heaters if re.search(r"\d+", e.designation) and re.search(r"\d+", e.designation).group() == num), None)
            if e_match:
                _add(f.id, e_match.id, f"Schutz {f.designation}→{e_match.designation}", f"Protection {f.designation}→{e_match.designation}")

            # F → K (controller with same number)
            k_match = next((k for k in controllers if re.search(r"\d+", k.designation) and re.search(r"\d+", k.designation).group() == num), None)
            if k_match:
                _add(f.id, k_match.id, f"Versorgung {f.designation}→{k_match.designation}", f"Supply {f.designation}→{k_match.designation}")

        # Pattern: T → B (transformer feeds sensor, e.g. T42→B42)
        for t in transformers:
            t_num = re.search(r"\d+", t.designation)
            if not t_num:
                continue
            for b in sensors:
                b_num = re.search(r"\d+", b.designation)
                if b_num and b_num.group() == t_num.group():
                    _add(t.id, b.id, f"Messung {t.designation}→{b.designation}", f"Measurement {t.designation}→{b.designation}")

        # Pattern: T → E (transformer feeds heater in same subsystem, e.g. T42→E42)
        for t in transformers:
            t_num = re.search(r"\d+", t.designation)
            if not t_num:
                continue
            for e in heaters:
                e_num = re.search(r"\d+", e.designation)
                if e_num and e_num.group() == t_num.group():
                    _add(t.id, e.id, f"Heizung {t.designation}→{e.designation}", f"Heater {t.designation}→{e.designation}")

        # Pattern: B (sensor) → K801 (main controller) signal wiring
        k801 = comp_by_desig.get("K801")
        if k801:
            for b in sensors:
                _add(b.id, k801.id, f"Signal {b.designation}→K801", f"Signal {b.designation}→K801")
            for s in switches:
                _add(s.id, k801.id, f"Signal {s.designation}→K801", f"Signal {s.designation}→K801")

    # Special: Q1 (main switch) → F21/F22 (main distribution)
    if "Q1" in comp_by_desig:
        q1 = comp_by_desig["Q1"]
        for f_desig in ("F21", "F22"):
            if f_desig in comp_by_desig:
                _add(q1.id, comp_by_desig[f_desig].id,
                     f"Hauptverteilung Q1→{f_desig}", f"Main distribution Q1→{f_desig}")

    # Special: A51 (control panel) → K801 (main controller)
    if "A51" in comp_by_desig and "K801" in comp_by_desig:
        _add(comp_by_desig["A51"].id, comp_by_desig["K801"].id,
             "Bedienpanel→Steuerung", "Control panel→Controller")

    return connections


# ---------------------------------------------------------------------------
# Phase 2b: Resolve cable connections to components
# ---------------------------------------------------------------------------

def _resolve_cable_connections(
    connections: list[MachineConnection],
    components: list[Component],
) -> list[MachineConnection]:
    """
    Try to link cables to their source/destination components using
    cable naming conventions and page references.

    EPLAN cable names follow patterns like:
    - WM201 → connects to Motor M201
    - WB452 → connects to Sensor B452
    - WE251 → connects to Heater E251
    - WM101-1 → power cable for M101
    - WM101-2 → signal cable for M101
    - WA801-1 → connects to controller A801 / K801
    """
    comp_by_desig = {}
    for c in components:
        comp_by_desig[c.designation] = c.id

    for conn in connections:
        name = conn.cable_name
        # Strip location prefix: "+MR1-WM201" → "WM201" or "+SS1-WA801-1" → "WA801-1"
        parts = name.split("-")
        # Find the W-prefixed part
        w_part = ""
        for i, p in enumerate(parts):
            if p.startswith("W") and len(p) > 1 and p[1].isalpha():
                # Rejoin remaining parts (e.g., "WA801" + "1" → "WA801-1")
                w_part = "-".join(parts[i:])
                break
        if not w_part:
            # Fallback: take everything after first '-'
            short = name.split("-", 1)[-1] if "-" in name else name
            if short.startswith("W"):
                w_part = short

        if not w_part:
            continue

        # Remove W prefix: "WM201" → "M201", "WA801-1" → "A801-1"
        target_raw = w_part[1:]
        # Remove cable sub-number suffix: "M101-1" → "M101", "A801-1" → "A801"
        target_desig = re.sub(r"-\d+$", "", target_raw)

        # Resolve to_component (field device end)
        if target_desig in comp_by_desig:
            conn.to_component = comp_by_desig[target_desig]
        else:
            # For controller cables like WA801 → try K801 (A→K mapping)
            if target_desig.startswith("A"):
                alt = "K" + target_desig[1:]
                if alt in comp_by_desig:
                    conn.to_component = comp_by_desig[alt]

        # Resolve from_component (cabinet-side / source end)
        # Heuristic: for field device cables, the source is typically the
        # protection device (F prefix) with same number, or the main switch
        target_letter = target_desig[0] if target_desig else ""

        if target_letter in ("M", "E", "B"):
            # Motor/Heater/Sensor cables: from_component = protection fuse F<number>
            fuse_desig = "F" + target_desig[1:]
            if fuse_desig in comp_by_desig:
                conn.from_component = comp_by_desig[fuse_desig]
            else:
                # Try contactor Q<number>
                q_desig = "Q" + target_desig[1:]
                if q_desig in comp_by_desig:
                    conn.from_component = comp_by_desig[q_desig]
        elif target_letter == "A" or target_letter == "K":
            # Controller/Assembly cables: from_component = K801 (main controller)
            if "K801" in comp_by_desig:
                conn.from_component = comp_by_desig["K801"]
        elif target_letter == "S":
            # Switch cables: from_component = K801
            if "K801" in comp_by_desig:
                conn.from_component = comp_by_desig["K801"]

    return connections


# ---------------------------------------------------------------------------
# Phase 3: Build the complete machine graph
# ---------------------------------------------------------------------------

def build_machine_graph(pdf_bytes: bytes) -> MachineGraph:
    """
    Main entry point: Analyze a full EPLAN-style PDF and build a machine graph.
    """
    graph = MachineGraph()

    # Extract raw data
    texts = _extract_texts(pdf_bytes)
    all_tables = _extract_tables(pdf_bytes)
    graph.pages_analyzed = len(texts)

    # Phase 1a: Cover page → technical data
    graph.technical_data = _extract_cover_data(texts)

    # Phase 1b: TOC → subsystems
    graph.subsystems = _extract_subsystems_from_toc(texts)

    # Phase 1c: Parts list → components
    parts_components = _extract_components_from_parts_list(texts, all_tables)

    # Phase 1d: Field devices → additional components
    field_components = _extract_field_devices(texts, all_tables)

    # Merge: parts list is primary, field devices fill gaps
    comp_by_id = {c.id: c for c in parts_components}
    for fc in field_components:
        if fc.id not in comp_by_id:
            comp_by_id[fc.id] = fc
        else:
            # Enrich existing with location if missing
            if not comp_by_id[fc.id].location and fc.location:
                comp_by_id[fc.id].location = fc.location

    graph.components = list(comp_by_id.values())

    # Phase 1e: Cable overview → connections
    graph.connections = _extract_cable_overview(texts, all_tables)

    # Phase 1f: Control overview → I/O mapping
    graph.io_assignments = _extract_control_overview(texts, all_tables)

    # Phase 1g: Circuit pages → component↔subsystem mapping
    subsystem_comp_map = _scan_circuit_pages_for_components(texts)

    # Phase 1h: Create fallback components from circuit pages + cable references
    # This recovers field devices (sensors, motors) not found in parts list
    fallback_components = _create_fallback_components(
        graph.components, subsystem_comp_map, graph.connections, texts,
    )
    for fc in fallback_components:
        comp_by_id[fc.id] = fc
    graph.components = list(comp_by_id.values())

    # Assign subsystems to components.
    # Priority 1: page_ref from parts list / field devices (e.g. &EFS=MA1+SS1/12)
    #   → extract sheet number → look up subsystem from circuit page titles
    # Priority 2: specificity-based assignment from circuit page scan
    sheet_to_sub = _build_sheet_to_subsystem_map(texts)

    desig_to_subsystems: dict[str, list[str]] = {}
    for sub_name, desig_list in subsystem_comp_map.items():
        for d in desig_list:
            desig_to_subsystems.setdefault(d, []).append(sub_name)

    # Compute specificity: number of unique component refs per subsystem
    sub_specificity = {sub: len(desigs) for sub, desigs in subsystem_comp_map.items()}

    for comp in graph.components:
        if comp.subsystem:
            continue  # already assigned

        # Priority 1: Use page_ref → sheet number → subsystem
        if comp.page_ref:
            m = re.search(r"/(\d+)", comp.page_ref)
            if m:
                sheet = int(m.group(1))
                sub = sheet_to_sub.get(sheet)
                if sub:
                    comp.subsystem = sub
                    continue

        # Priority 2: specificity-based assignment
        candidates = desig_to_subsystems.get(comp.designation, [])
        if not candidates:
            continue
        # Pick the most specific subsystem (fewest total component refs)
        best = min(candidates, key=lambda s: sub_specificity.get(s, 999))
        comp.subsystem = best

    # Update subsystem objects with component ids
    for sub_name, desig_list in subsystem_comp_map.items():
        for sub in graph.subsystems:
            if sub.name == sub_name:
                for comp in graph.components:
                    if comp.designation in desig_list and comp.id not in sub.component_ids:
                        sub.component_ids.append(comp.id)

    # Phase 1i: Create missing subsystems from circuit page scan
    # (catches subsystems that weren't found in TOC but appear as page titles)
    existing_sub_names = {s.name for s in graph.subsystems}
    for sub_name in subsystem_comp_map:
        if sub_name not in existing_sub_names:
            comp_ids = []
            for comp in graph.components:
                if comp.subsystem == sub_name:
                    comp_ids.append(comp.id)
            graph.subsystems.append(Subsystem(
                name=sub_name,
                component_ids=comp_ids,
            ))

    # Phase 2: Resolve cable → component connections
    graph.connections = _resolve_cable_connections(graph.connections, graph.components)

    # Phase 2a: Infer internal wiring from IEC 81346 patterns
    internal = _infer_internal_connections(graph.components, subsystem_comp_map)
    graph.connections.extend(internal)

    # Validation
    if not graph.components:
        graph.warnings.append("No components found. The PDF may not be an EPLAN-formatted schematic.")
    if not graph.connections:
        graph.warnings.append("No cable connections found.")
    if not graph.subsystems:
        graph.warnings.append("No subsystems detected from table of contents.")

    return graph
