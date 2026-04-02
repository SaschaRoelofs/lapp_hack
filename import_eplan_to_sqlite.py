"""Import parsed EPLAN export JSON files into SQLite."""

from __future__ import annotations

import argparse
from pathlib import Path

from eplan_sqlite import DEFAULT_DB_PATH, import_directory_to_sqlite


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import EPLAN export JSON files into SQLite.")
    parser.add_argument(
        "source_dir",
        nargs="?",
        default=str(Path(__file__).parent),
        help="Directory containing functions.json, cables.json and connections.json.",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    summary = import_directory_to_sqlite(source_dir=args.source_dir, db_path=args.db_path)

    print(f"SQLite DB:            {summary.db_path}")
    print(f"Source directory:     {summary.source_dir}")
    print(f"Functions imported:   {summary.functions_count}")
    print(f"Cables imported:      {summary.cables_count}")
    print(f"Connections imported: {summary.connections_count}")
    print(f"Resolved connections: {summary.resolved_connections_count}")
    print(f"Unresolved connections: {summary.unresolved_connections_count}")


if __name__ == "__main__":
    main()