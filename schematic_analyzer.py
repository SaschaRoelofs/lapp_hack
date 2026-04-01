"""
Schematic Analyzer – Extracts cable/wiring information from PDF schematics.

Hybrid approach:
1. Text extraction (PyMuPDF + pdfplumber) for tabular data (cable lists, terminal plans)
2. Vision LLM (via OpenRouter) for graphical schematic pages

Outputs a structured cable list with type, cross-section, core count, colors,
connections (from-to), lengths, and connectors/terminals.
"""

from __future__ import annotations

import base64
import io
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber
from openai import OpenAI

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Terminal:
    device: str = ""
    terminal: str = ""
    pin: str = ""

@dataclass
class Connection:
    from_terminal: Terminal = field(default_factory=Terminal)
    to_terminal: Terminal = field(default_factory=Terminal)

@dataclass
class Cable:
    designation: str = ""
    cable_type: str = ""
    cross_section_mm2: Optional[float] = None
    num_cores: Optional[int] = None
    core_colors: list[str] = field(default_factory=list)
    length_m: Optional[float] = None
    connections: list[Connection] = field(default_factory=list)
    connectors: list[str] = field(default_factory=list)
    source_page: Optional[int] = None
    confidence: float = 0.0

@dataclass
class AnalysisResult:
    cables: list[Cable] = field(default_factory=list)
    pages_analyzed: int = 0
    pages_text: int = 0
    pages_vision: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cables": [asdict(c) for c in self.cables],
            "pages_analyzed": self.pages_analyzed,
            "pages_text": self.pages_text,
            "pages_vision": self.pages_vision,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# PDF processing helpers
# ---------------------------------------------------------------------------

def pdf_to_page_images(pdf_bytes: bytes, dpi: int = 200) -> list[bytes]:
    """Convert each PDF page to a PNG image (bytes)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    for page in doc:
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def extract_text_per_page(pdf_bytes: bytes) -> list[str]:
    """Extract text content from each page using PyMuPDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = []
    for page in doc:
        texts.append(page.get_text())
    doc.close()
    return texts


def extract_tables_per_page(pdf_bytes: bytes) -> list[list[list]]:
    """Extract tables from each page using pdfplumber."""
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables() or []
        all_tables.append(tables)
    pdf.close()
    return all_tables


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

# Common cable designation patterns
CABLE_PATTERNS = [
    r"ÖLFLEX",
    r"NYM[\s\-]",
    r"NYY[\s\-]",
    r"H[0-9]{2}[A-Z]{1,2}[\s\-]",
    r"NSHXAFÖ",
    r"NHXMH",
    r"LIYY",
    r"LiYCY",
    r"\d+\s*[xXGg]\s*\d+[,\.]\d+",  # e.g. "3x1,5" or "5G2.5"
    r"mm²",
    r"AWG",
]

TABLE_KEYWORDS = [
    "Kabelliste", "cable list", "Klemmplan", "terminal", "Klemme",
    "Verbindung", "connection", "Stecker", "connector", "Leitung",
    "Querschnitt", "cross.?section", "Aderzahl", "cores",
    "Artikel", "article", "Bestell", "order",
]


def classify_page(text: str, tables: list[list]) -> str:
    """
    Classify a page as 'table', 'schematic', or 'other'.
    - 'table': Contains structured cable/terminal data in table form
    - 'schematic': Contains schematic drawing with cable references
    - 'other': Title pages, legends, etc.
    """
    text_lower = text.lower()
    has_tables = len(tables) > 0 and any(len(t) > 1 for t in tables)
    has_cable_refs = any(re.search(p, text, re.IGNORECASE) for p in CABLE_PATTERNS)
    has_table_keywords = any(re.search(kw, text_lower) for kw in TABLE_KEYWORDS)

    if has_tables and (has_cable_refs or has_table_keywords):
        return "table"
    if has_cable_refs:
        return "schematic"
    if len(text.strip()) < 50:
        return "other"
    return "other"


# ---------------------------------------------------------------------------
# Text-based extraction (tables)
# ---------------------------------------------------------------------------

def parse_cross_section(value: str) -> Optional[float]:
    """Parse a cross-section value like '1,5' or '2.5' to float."""
    if not value:
        return None
    cleaned = value.strip().replace(",", ".").replace("mm²", "").replace("mm2", "").strip()
    match = re.search(r"(\d+\.?\d*)", cleaned)
    if match:
        return float(match.group(1))
    return None


def parse_cores_spec(spec: str) -> tuple[Optional[int], Optional[float]]:
    """Parse specs like '3 G 1,5' or '5x2.5' → (num_cores, cross_section)."""
    if not spec:
        return None, None
    spec = spec.strip()
    m = re.match(r"(\d+)\s*[xXGg×]\s*(\d+[,.]?\d*)", spec)
    if m:
        cores = int(m.group(1))
        cs = float(m.group(2).replace(",", "."))
        return cores, cs
    return None, None


def extract_cables_from_tables(tables: list[list], page_num: int) -> list[Cable]:
    """Extract cable information from parsed tables."""
    cables = []
    for table in tables:
        if len(table) < 2:
            continue

        header = table[0]
        if not header:
            continue
        header_lower = [str(h).lower().strip() if h else "" for h in header]

        col_map = {}
        for i, h in enumerate(header_lower):
            if any(k in h for k in ["kabel", "cable", "leitung", "bezeichnung", "designation"]):
                col_map["designation"] = i
            elif any(k in h for k in ["typ", "type", "kabeltyp"]):
                col_map["cable_type"] = i
            elif any(k in h for k in ["querschnitt", "cross", "mm²", "mm2", "section"]):
                col_map["cross_section"] = i
            elif any(k in h for k in ["ader", "core", "pole", "leiter"]):
                col_map["cores"] = i
            elif any(k in h for k in ["farbe", "color", "colour"]):
                col_map["colors"] = i
            elif any(k in h for k in ["länge", "length", "meter"]):
                col_map["length"] = i
            elif any(k in h for k in ["von", "from", "quelle", "source"]):
                col_map["from"] = i
            elif any(k in h for k in ["nach", "to", "ziel", "dest"]):
                col_map["to"] = i
            elif any(k in h for k in ["stecker", "connector", "klemme", "terminal"]):
                col_map["connector"] = i

        for row in table[1:]:
            if not row or all(not cell for cell in row):
                continue

            cable = Cable(source_page=page_num, confidence=0.85)

            if "designation" in col_map and col_map["designation"] < len(row):
                cable.designation = str(row[col_map["designation"]] or "").strip()
            if "cable_type" in col_map and col_map["cable_type"] < len(row):
                cable.cable_type = str(row[col_map["cable_type"]] or "").strip()
            if "cross_section" in col_map and col_map["cross_section"] < len(row):
                cable.cross_section_mm2 = parse_cross_section(str(row[col_map["cross_section"]] or ""))
            if "cores" in col_map and col_map["cores"] < len(row):
                val = str(row[col_map["cores"]] or "").strip()
                m = re.search(r"(\d+)", val)
                if m:
                    cable.num_cores = int(m.group(1))
            if "colors" in col_map and col_map["colors"] < len(row):
                val = str(row[col_map["colors"]] or "").strip()
                if val:
                    cable.core_colors = [c.strip() for c in re.split(r"[,;/]", val) if c.strip()]
            if "length" in col_map and col_map["length"] < len(row):
                val = str(row[col_map["length"]] or "").strip().replace(",", ".")
                m = re.search(r"(\d+\.?\d*)", val)
                if m:
                    cable.length_m = float(m.group(1))
            if "connector" in col_map and col_map["connector"] < len(row):
                val = str(row[col_map["connector"]] or "").strip()
                if val:
                    cable.connectors.append(val)

            conn = Connection()
            if "from" in col_map and col_map["from"] < len(row):
                conn.from_terminal = Terminal(device=str(row[col_map["from"]] or "").strip())
            if "to" in col_map and col_map["to"] < len(row):
                conn.to_terminal = Terminal(device=str(row[col_map["to"]] or "").strip())
            if conn.from_terminal.device or conn.to_terminal.device:
                cable.connections.append(conn)

            if not cable.cable_type and not cable.designation and cable.cross_section_mm2 is None:
                # Try to parse a combined spec from any non-empty cell
                for cell in row:
                    cell_str = str(cell or "")
                    cores, cs = parse_cores_spec(cell_str)
                    if cores and cs:
                        cable.num_cores = cores
                        cable.cross_section_mm2 = cs
                        break
                    for pat in CABLE_PATTERNS[:6]:
                        if re.search(pat, cell_str, re.IGNORECASE):
                            cable.cable_type = cell_str.strip()
                            break

            if cable.cable_type or cable.designation or cable.cross_section_mm2 is not None:
                cables.append(cable)

    return cables


def extract_cables_from_text(text: str, page_num: int) -> list[Cable]:
    """Extract cable references from free text using regex patterns."""
    cables = []

    # Pattern: cable type + core spec, e.g. "ÖLFLEX CONTROL TM 3G1,5"
    pattern = re.compile(
        r"((?:ÖLFLEX|NYM|NYY|H\d{2}\w+|NHXMH|NSHXAFÖ|LIYY|LiYCY)\S*[\s\w\-®]*?)"
        r"\s+(\d+)\s*[xXGg×]\s*(\d+[,.]?\d*)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        cable = Cable(
            cable_type=m.group(0).strip(),
            num_cores=int(m.group(2)),
            cross_section_mm2=float(m.group(3).replace(",", ".")),
            source_page=page_num,
            confidence=0.7,
        )
        cables.append(cable)

    # Pattern: standalone core specs like "5x2,5mm²"
    spec_pattern = re.compile(r"(\d+)\s*[xXGg×]\s*(\d+[,.]?\d*)\s*mm", re.IGNORECASE)
    for m in spec_pattern.finditer(text):
        cores = int(m.group(1))
        cs = float(m.group(2).replace(",", "."))
        # Avoid duplicates from the first pattern
        if not any(c.num_cores == cores and c.cross_section_mm2 == cs for c in cables):
            cable = Cable(
                num_cores=cores,
                cross_section_mm2=cs,
                source_page=page_num,
                confidence=0.5,
            )
            cables.append(cable)

    return cables


# ---------------------------------------------------------------------------
# Vision LLM extraction
# ---------------------------------------------------------------------------

VISION_SYSTEM_PROMPT = """You are an expert electrical engineer analyzing schematic diagrams (Stromlaufpläne / Schaltpläne).
Extract ALL cable and wiring information visible in the image.

For each cable/wire found, extract:
- designation: Cable label/identifier (e.g. "W1", "K3", "L1")
- cable_type: Cable type designation (e.g. "ÖLFLEX CONTROL TM", "NYM-J")
- cross_section_mm2: Cross-section in mm² (number only)
- num_cores: Number of cores/conductors (number only)
- core_colors: List of wire colors (e.g. ["BN", "BU", "GN/YE"])
- length_m: Cable length in meters if shown (number only)
- from_device: Source device/component name
- from_terminal: Source terminal/pin
- to_device: Destination device/component name
- to_terminal: Destination terminal/pin
- connectors: Any connectors or terminal blocks mentioned

Respond ONLY with a JSON array. Each element represents one cable:
```json
[
  {
    "designation": "W1",
    "cable_type": "NYM-J",
    "cross_section_mm2": 2.5,
    "num_cores": 3,
    "core_colors": ["BN", "BU", "GN/YE"],
    "length_m": 12.0,
    "from_device": "Q1",
    "from_terminal": "2",
    "to_device": "K1",
    "to_terminal": "A1",
    "connectors": ["X1"]
  }
]
```

If a field is not visible or unclear, use null. Only include cables you can clearly identify.
If the page contains no cable/wiring information, return an empty array: []"""


def _get_openrouter_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Set it to your OpenRouter API key to enable vision analysis."
        )
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def analyze_page_with_vision(
    image_png: bytes,
    page_num: int,
    model: str = "openai/gpt-5.4-pro",
) -> list[Cable]:
    """Send a page image to the vision LLM and parse the structured response."""
    client = _get_openrouter_client()

    b64 = base64.b64encode(image_png).decode("utf-8")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Analyze this schematic diagram (page {page_num + 1}). "
                                "Extract all cable and wiring information.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                        },
                    },
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.1,
    )

    content = response.choices[0].message.content or ""
    return _parse_vision_response(content, page_num)


def _parse_vision_response(content: str, page_num: int) -> list[Cable]:
    """Parse the JSON response from the vision LLM into Cable objects."""
    import json

    # Extract JSON from potential markdown code block
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON array
        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            return []

    try:
        items = json.loads(json_str)
    except json.JSONDecodeError:
        return []

    if not isinstance(items, list):
        return []

    cables = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cable = Cable(
            designation=str(item.get("designation") or ""),
            cable_type=str(item.get("cable_type") or ""),
            cross_section_mm2=_safe_float(item.get("cross_section_mm2")),
            num_cores=_safe_int(item.get("num_cores")),
            core_colors=item.get("core_colors") or [],
            length_m=_safe_float(item.get("length_m")),
            source_page=page_num,
            confidence=0.75,
        )

        conn = Connection()
        from_dev = str(item.get("from_device") or "")
        from_term = str(item.get("from_terminal") or "")
        to_dev = str(item.get("to_device") or "")
        to_term = str(item.get("to_terminal") or "")
        if from_dev or to_dev:
            conn.from_terminal = Terminal(device=from_dev, terminal=from_term)
            conn.to_terminal = Terminal(device=to_dev, terminal=to_term)
            cable.connections.append(conn)

        connectors = item.get("connectors") or []
        if isinstance(connectors, list):
            cable.connectors = [str(c) for c in connectors]

        cables.append(cable)

    return cables


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Deduplication & merging
# ---------------------------------------------------------------------------

def _cable_key(c: Cable) -> str:
    """Generate a key for deduplication."""
    parts = [
        c.designation.lower().strip(),
        c.cable_type.lower().strip(),
        str(c.cross_section_mm2 or ""),
        str(c.num_cores or ""),
    ]
    return "|".join(parts)


def merge_cables(cables: list[Cable]) -> list[Cable]:
    """Deduplicate and merge cable entries from different sources."""
    groups: dict[str, list[Cable]] = {}
    for cable in cables:
        key = _cable_key(cable)
        if key == "|||":
            continue
        groups.setdefault(key, []).append(cable)

    merged = []
    for group in groups.values():
        best = max(group, key=lambda c: c.confidence)

        # Enrich from other entries in the group
        for other in group:
            if other is best:
                continue
            if not best.cable_type and other.cable_type:
                best.cable_type = other.cable_type
            if best.cross_section_mm2 is None and other.cross_section_mm2 is not None:
                best.cross_section_mm2 = other.cross_section_mm2
            if best.num_cores is None and other.num_cores is not None:
                best.num_cores = other.num_cores
            if not best.core_colors and other.core_colors:
                best.core_colors = other.core_colors
            if best.length_m is None and other.length_m is not None:
                best.length_m = other.length_m
            if not best.connections and other.connections:
                best.connections = other.connections
            if not best.connectors and other.connectors:
                best.connectors = other.connectors

        merged.append(best)

    return merged


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------

def analyze_pdf(
    pdf_bytes: bytes,
    use_vision: bool = True,
    vision_model: str = "openai/gpt-5.4-pro",
) -> AnalysisResult:
    """
    Analyze a PDF schematic and extract cable/wiring information.

    Args:
        pdf_bytes: Raw PDF file content
        use_vision: Whether to use Vision LLM for graphical pages
        vision_model: OpenRouter model identifier for vision analysis

    Returns:
        AnalysisResult with extracted cables and metadata
    """
    result = AnalysisResult()

    # Step 1: Extract text and tables from all pages
    page_texts = extract_text_per_page(pdf_bytes)
    page_tables = extract_tables_per_page(pdf_bytes)
    result.pages_analyzed = len(page_texts)

    # Step 2: Prepare page images if vision is enabled
    page_images: list[bytes] = []
    if use_vision:
        try:
            page_images = pdf_to_page_images(pdf_bytes)
        except Exception as e:
            result.warnings.append(f"Could not render page images: {e}")
            use_vision = False

    all_cables: list[Cable] = []

    # Step 3: Process each page
    for i, (text, tables) in enumerate(zip(page_texts, page_tables)):
        page_type = classify_page(text, tables)

        if page_type == "table":
            # Text-based extraction from tables
            table_cables = extract_cables_from_tables(tables, i)
            text_cables = extract_cables_from_text(text, i)
            all_cables.extend(table_cables)
            all_cables.extend(text_cables)
            result.pages_text += 1

        elif page_type == "schematic":
            # Try text extraction first
            text_cables = extract_cables_from_text(text, i)
            all_cables.extend(text_cables)

            # Use vision for graphical analysis
            if use_vision and i < len(page_images):
                try:
                    vision_cables = analyze_page_with_vision(
                        page_images[i], i, model=vision_model
                    )
                    all_cables.extend(vision_cables)
                    result.pages_vision += 1
                except Exception as e:
                    result.warnings.append(f"Vision analysis failed for page {i + 1}: {e}")
                    result.pages_text += 1
            else:
                result.pages_text += 1

        # 'other' pages are skipped

    # Step 4: Deduplicate and merge
    result.cables = merge_cables(all_cables)

    if not result.cables:
        result.warnings.append(
            "No cables found. The PDF may not contain recognizable schematic data, "
            "or the format is not yet supported."
        )

    return result
