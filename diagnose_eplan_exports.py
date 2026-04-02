"""Diagnostic script for the EPLAN export JSON files."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from eplan_exports import load_export_bundle


sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    base_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    bundle = load_export_bundle(base_path)
    resolutions = bundle.resolve_connections()

    resolved = [resolution for resolution in resolutions if resolution.is_resolved]
    unresolved = [resolution for resolution in resolutions if not resolution.is_resolved]
    unresolved_reasons = Counter(reason for resolution in unresolved for reason in resolution.unresolved_reasons)
    cable_function_count = len(bundle.functions.cable_functions_by_name())
    orphan_cables = bundle.orphan_cable_names()

    print(f"Base path:           {base_path}")
    print(f"Functions:           {len(bundle.functions.functions)}")
    print(f"Function categories: {len(bundle.functions.category_counts())}")
    print(f"Cable functions:     {cable_function_count}")
    print(f"Cables:              {len(bundle.cables.cables)}")
    print(f"Connections:         {len(bundle.connections.connections)}")
    print(f"Resolved connections:{len(resolved)}")
    print(f"Unresolved connections: {len(unresolved)}")

    if orphan_cables:
        print("\nOrphan cables without Cable function:")
        for cable_name in orphan_cables:
            print(f"  {cable_name}")

    if unresolved_reasons:
        print("\nUnresolved reasons:")
        for reason, count in unresolved_reasons.most_common():
            print(f"  {reason:24s} {count}")

    sample_matches = [
        resolution
        for resolution in resolved
        if resolution.matched_cable_name in {"+A1-WD1", "+A1-WD2", "+B1.X1-WZ1"}
    ]
    if sample_matches:
        print("\nSample resolved matches:")
        for resolution in sample_matches[:10]:
            print(
                f"  idx={resolution.connection_index:3d} "
                f"cable={resolution.matched_cable_name:12s} "
                f"wire={resolution.effective_wire_number or '-':6s} "
                f"cable_functions={len(resolution.matched_cable_function_names)}"
            )


if __name__ == "__main__":
    main()