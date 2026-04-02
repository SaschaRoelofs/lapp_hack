"""
Diagnostic tool: Compare build_machine_graph() output against the golden fixture.

Usage:
    python diagnose_parser.py <path_to_pdf>
    python diagnose_parser.py              # uses default path if PDF found next to script
"""

import json
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from machine_analyzer import build_machine_graph, _extract_texts, _extract_tables, _detect_page_type


FIXTURE_PATH = Path(__file__).parent / "machine_graph_kkt_cboxx100.json"


def load_fixture() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def diagnose_page_classification(pdf_bytes: bytes):
    """Print page-by-page classification + first 200 chars of text."""
    texts = _extract_texts(pdf_bytes)
    print(f"\n{'='*70}")
    print(f"PAGE CLASSIFICATION ({len(texts)} pages)")
    print(f"{'='*70}")

    type_counts: dict[str, int] = {}
    for i, text in enumerate(texts):
        ptype = _detect_page_type(text)
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
        preview = text[:200].replace("\n", " ").strip()
        print(f"  Page {i+1:2d}: {ptype:20s} | {preview}")

    print(f"\nSummary: {type_counts}")


def diagnose_tables(pdf_bytes: bytes):
    """Print table info for key pages."""
    texts = _extract_texts(pdf_bytes)
    all_tables = _extract_tables(pdf_bytes)
    print(f"\n{'='*70}")
    print("TABLE EXTRACTION DETAILS")
    print(f"{'='*70}")

    for i, text in enumerate(texts):
        ptype = _detect_page_type(text)
        if ptype not in ("parts_list", "cable_overview", "field_devices", "control_overview"):
            continue

        tables = all_tables[i] if i < len(all_tables) else []
        print(f"\n  Page {i+1} ({ptype}): {len(tables)} table(s)")
        for ti, table in enumerate(tables):
            print(f"    Table {ti}: {len(table)} rows")
            if table:
                header = table[0]
                print(f"      Header ({len(header)} cols): {header}")
                if len(table) > 1:
                    print(f"      Row 1: {table[1]}")


def compare_components(parsed: dict, fixture: dict):
    """Compare parsed vs expected components."""
    print(f"\n{'='*70}")
    print("COMPONENT COMPARISON")
    print(f"{'='*70}")

    parsed_ids = {c["id"] for c in parsed["components"]}
    fixture_ids = {c["id"] for c in fixture["components"]}

    matched = parsed_ids & fixture_ids
    missing = fixture_ids - parsed_ids
    extra = parsed_ids - fixture_ids

    print(f"  Parsed:  {len(parsed_ids)}")
    print(f"  Golden:  {len(fixture_ids)}")
    print(f"  Matched: {len(matched)}")
    print(f"  Missing: {len(missing)}")
    print(f"  Extra:   {len(extra)}")

    if missing:
        print(f"\n  MISSING components (in fixture but not parsed):")
        for cid in sorted(missing):
            fc = next(c for c in fixture["components"] if c["id"] == cid)
            print(f"    {cid:20s} | {fc.get('component_type',''):12s} | {fc.get('description_de','')}")

    if extra:
        print(f"\n  EXTRA components (parsed but not in fixture):")
        for cid in sorted(extra):
            pc = next(c for c in parsed["components"] if c["id"] == cid)
            print(f"    {cid:20s} | {pc.get('component_type',''):12s} | {pc.get('description_de','')}")

    # Compare subsystem assignments for matched components
    sub_match = 0
    sub_mismatch = 0
    for cid in sorted(matched):
        pc = next(c for c in parsed["components"] if c["id"] == cid)
        fc = next(c for c in fixture["components"] if c["id"] == cid)
        if pc.get("subsystem") == fc.get("subsystem"):
            sub_match += 1
        else:
            sub_mismatch += 1
            print(f"    Subsystem mismatch: {cid} -> parsed='{pc.get('subsystem','')}' expected='{fc.get('subsystem','')}'")

    print(f"\n  Subsystem assignments: {sub_match} correct, {sub_mismatch} mismatched")

    # Compare field-level data quality for matched components
    FIELDS = ["description_de", "manufacturer", "order_number", "technical_specs", "sap_number"]
    field_stats: dict[str, int] = {f: 0 for f in FIELDS}
    field_total = len(matched)
    for cid in sorted(matched):
        pc = next(c for c in parsed["components"] if c["id"] == cid)
        fc = next(c for c in fixture["components"] if c["id"] == cid)
        for f in FIELDS:
            if pc.get(f) == fc.get(f):
                field_stats[f] += 1

    print(f"\n  Field-level accuracy ({field_total} matched components):")
    for f in FIELDS:
        pct = field_stats[f] / field_total * 100 if field_total else 0
        print(f"    {f:20s}: {field_stats[f]:3d}/{field_total} ({pct:.0f}%)")


def _is_internal(conn: dict) -> bool:
    """Classify a connection as internal wiring vs external cable."""
    cn = conn.get("cable_name", "")
    ct = conn.get("connection_type", "")
    if ct == "internal_wiring":
        return True
    if cn == "intern" or cn.startswith("INT_"):
        return True
    return False


def compare_connections(parsed: dict, fixture: dict):
    """Compare parsed vs expected connections."""
    print(f"\n{'='*70}")
    print("CONNECTION COMPARISON")
    print(f"{'='*70}")

    # --- External cables: compare by cable_name ---
    parsed_ext = [c for c in parsed["connections"] if not _is_internal(c)]
    fixture_ext = [c for c in fixture["connections"] if not _is_internal(c)]
    parsed_int = [c for c in parsed["connections"] if _is_internal(c)]
    fixture_int = [c for c in fixture["connections"] if _is_internal(c)]

    parsed_ext_names = {c["cable_name"] for c in parsed_ext}
    fixture_ext_names = {c["cable_name"] for c in fixture_ext}

    print(f"  Parsed total:     {len(parsed['connections'])} ({len(parsed_ext)} ext, {len(parsed_int)} int)")
    print(f"  Golden total:     {len(fixture['connections'])} ({len(fixture_ext)} ext, {len(fixture_int)} int)")

    matched_ext = parsed_ext_names & fixture_ext_names
    missing_ext = fixture_ext_names - parsed_ext_names
    extra_ext = parsed_ext_names - fixture_ext_names

    print(f"\n  External cables matched: {len(matched_ext)}/{len(fixture_ext_names)}")
    if missing_ext:
        print(f"  MISSING external cables:")
        for cn in sorted(missing_ext):
            fc = next(c for c in fixture_ext if c["cable_name"] == cn)
            print(f"    {cn:25s} | {fc.get('cable_type',''):20s} | to={fc.get('to_component','')}")
    if extra_ext:
        print(f"  EXTRA external cables: {len(extra_ext)}")
        for cn in sorted(extra_ext):
            pc = next(c for c in parsed_ext if c["cable_name"] == cn)
            print(f"    {cn:25s} | {pc.get('cable_type',''):20s}")

    # --- Internal wiring: compare by (from_component, to_component) pair ---
    parsed_int_pairs = {(c.get("from_component", ""), c.get("to_component", "")) for c in parsed_int}
    fixture_int_pairs = {(c.get("from_component", ""), c.get("to_component", "")) for c in fixture_int}

    matched_int = parsed_int_pairs & fixture_int_pairs
    missing_int = fixture_int_pairs - parsed_int_pairs
    extra_int = parsed_int_pairs - fixture_int_pairs

    print(f"\n  Internal wiring matched: {len(matched_int)}/{len(fixture_int_pairs)}")
    if missing_int:
        print(f"  MISSING internal wiring:")
        for fr, to in sorted(missing_int):
            fc = next((c for c in fixture_int if c.get("from_component") == fr and c.get("to_component") == to), {})
            print(f"    {fr:20s} -> {to:20s} | {fc.get('function_de','')}")
    if extra_int:
        print(f"  EXTRA internal wiring: {len(extra_int)}")
        for fr, to in sorted(extra_int):
            print(f"    {fr:20s} -> {to:20s}")

    # Check from/to component resolution
    resolved = 0
    unresolved_to = 0
    unresolved_from = 0
    for c in parsed["connections"]:
        if c.get("to_component"):
            resolved += 1
        else:
            unresolved_to += 1
        if not c.get("from_component"):
            unresolved_from += 1

    print(f"\n  To-component resolved:   {resolved}/{len(parsed['connections'])}")
    print(f"  From-component missing:  {unresolved_from}/{len(parsed['connections'])}")


def compare_subsystems(parsed: dict, fixture: dict):
    """Compare parsed vs expected subsystems."""
    print(f"\n{'='*70}")
    print("SUBSYSTEM COMPARISON")
    print(f"{'='*70}")

    parsed_names = {s["name"] for s in parsed["subsystems"]}
    fixture_names = {s["name"] for s in fixture["subsystems"]}

    matched = parsed_names & fixture_names
    missing = fixture_names - parsed_names
    extra = parsed_names - fixture_names

    print(f"  Parsed:  {len(parsed_names)}")
    print(f"  Golden:  {len(fixture_names)}")
    print(f"  Matched: {len(matched)}")
    print(f"  Missing: {len(missing)}")
    print(f"  Extra:   {len(extra)}")

    if missing:
        print(f"\n  MISSING subsystems:")
        for n in sorted(missing):
            print(f"    {n}")
    if extra:
        print(f"\n  EXTRA subsystems:")
        for n in sorted(extra):
            print(f"    {n}")


def compare_io(parsed: dict, fixture: dict):
    """Compare parsed vs expected I/O assignments."""
    print(f"\n{'='*70}")
    print("I/O ASSIGNMENT COMPARISON")
    print(f"{'='*70}")

    p_io = parsed["io_assignments"]
    f_io = fixture["io_assignments"]

    print(f"  Parsed:  {len(p_io)}")
    print(f"  Golden:  {len(f_io)}")

    # Compare by (connector, pin) as primary key
    parsed_keys = {(io.get("connector", ""), io["pin"]) for io in p_io}
    fixture_keys = {(io.get("connector", ""), io["pin"]) for io in f_io}

    matched_cp = parsed_keys & fixture_keys
    missing_cp = fixture_keys - parsed_keys

    # Fallback: also compare by (pin, function_de) for parsers that don't extract connector
    parsed_pins = {(io["pin"], io.get("function_de", "")) for io in p_io}
    fixture_pins = {(io["pin"], io.get("function_de", "")) for io in f_io}
    matched_pf = parsed_pins & fixture_pins
    missing_pf = fixture_pins - parsed_pins

    print(f"  By (connector, pin): {len(matched_cp)}/{len(fixture_keys)} matched")
    print(f"  By (pin, function):  {len(matched_pf)}/{len(fixture_pins)} matched")

    # Check connector coverage
    fixture_connectors = {io.get("connector", "") for io in f_io if io.get("connector")}
    parsed_connectors = {io.get("connector", "") for io in p_io if io.get("connector")}
    print(f"  Connectors: parsed {len(parsed_connectors)}, golden {len(fixture_connectors)}")

    if missing_pf:
        print(f"\n  MISSING I/O assignments (by pin+function):")
        for pin, func in sorted(missing_pf, key=lambda x: x[0]):
            print(f"    Pin {pin:4s} | {func}")


def compare_technical_data(parsed: dict, fixture: dict):
    """Compare parsed vs expected technical data."""
    print(f"\n{'='*70}")
    print("TECHNICAL DATA COMPARISON")
    print(f"{'='*70}")

    ptd = parsed["technical_data"]
    ftd = fixture["technical_data"]

    for key in ftd:
        pval = ptd.get(key, "")
        fval = ftd[key]
        status = "OK" if pval == fval else ("PARTIAL" if pval and fval and pval in fval or fval in pval else ("MISS" if not pval else "DIFF"))
        if status != "OK":
            print(f"  {status:7s} {key:20s}: parsed='{pval}' expected='{fval}'")
        else:
            print(f"  {status:7s} {key:20s}: '{pval}'")


def main():
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        # Try to find PDF in common locations
        candidates = list(Path(__file__).parent.glob("*.pdf"))
        if not candidates:
            print("Usage: python diagnose_parser.py <path_to_pdf>")
            print("No PDF files found in script directory.")
            sys.exit(1)
        pdf_path = candidates[0]
        print(f"Using PDF: {pdf_path}")

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)

    if not FIXTURE_PATH.exists():
        print(f"Golden fixture not found: {FIXTURE_PATH}")
        print("Run: python build_fixture.py")
        sys.exit(1)

    pdf_bytes = pdf_path.read_bytes()
    fixture = load_fixture()

    print(f"\n{'#'*70}")
    print(f"# DIAGNOSTIC REPORT: {pdf_path.name}")
    print(f"# PDF size: {len(pdf_bytes):,} bytes")
    print(f"{'#'*70}")

    # Step 1: Page classification
    diagnose_page_classification(pdf_bytes)

    # Step 2: Table extraction details
    diagnose_tables(pdf_bytes)

    # Step 3: Run the full parser
    print(f"\n{'='*70}")
    print("RUNNING build_machine_graph()...")
    print(f"{'='*70}")
    graph = build_machine_graph(pdf_bytes)
    parsed = graph.to_dict()

    print(f"  Pages analyzed: {parsed['pages_analyzed']}")
    print(f"  Components:     {len(parsed['components'])}")
    print(f"  Connections:    {len(parsed['connections'])}")
    print(f"  Subsystems:     {len(parsed['subsystems'])}")
    print(f"  I/O:            {len(parsed['io_assignments'])}")
    print(f"  Warnings:       {parsed['warnings']}")

    # Step 4: Comparisons
    compare_technical_data(parsed, fixture)
    compare_components(parsed, fixture)
    compare_connections(parsed, fixture)
    compare_subsystems(parsed, fixture)
    compare_io(parsed, fixture)

    # Summary
    comp_pct = len({c["id"] for c in parsed["components"]} & {c["id"] for c in fixture["components"]}) / len(fixture["components"]) * 100
    ext_cables = {c["cable_name"] for c in fixture["connections"] if c.get("cable_type")}
    conn_pct = len({c["cable_name"] for c in parsed["connections"]} & ext_cables) / len(ext_cables) * 100 if ext_cables else 0
    sub_pct = len({s["name"] for s in parsed["subsystems"]} & {s["name"] for s in fixture["subsystems"]}) / len(fixture["subsystems"]) * 100
    io_pct = len(parsed["io_assignments"]) / len(fixture["io_assignments"]) * 100 if fixture["io_assignments"] else 0

    print(f"\n{'#'*70}")
    print(f"# SUMMARY SCORES")
    print(f"#   Components: {comp_pct:.0f}% ({len(parsed['components'])}/{len(fixture['components'])})")
    print(f"#   Ext Cables: {conn_pct:.0f}% ({len({c['cable_name'] for c in parsed['connections']} & ext_cables)}/{len(ext_cables)})")
    print(f"#   Subsystems: {sub_pct:.0f}% ({len({s['name'] for s in parsed['subsystems']} & {s['name'] for s in fixture['subsystems']})}/{len(fixture['subsystems'])})")
    print(f"#   I/O:        {io_pct:.0f}% ({len(parsed['io_assignments'])}/{len(fixture['io_assignments'])})")
    print(f"{'#'*70}")


if __name__ == "__main__":
    main()
