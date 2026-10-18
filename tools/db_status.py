"""Report the two-state status of a stellariso database (all families).

Compares what a database actually holds against every family's declared
design and writes the completion report: per family the source's own
declarations, then one line per product — ``complete``, or
``incomplete`` with the per-part detail (which part is missing, which
part is nonconforming and why) — plus the superseded directories and
the automatic-fetch plan. The report is the review artifact: marked
data is never deleted or refetched by this tool.

    python tools/db_status.py C:/Users/me/stellariso-database

Writes ``db_status.md`` and ``db_status.json`` next to the database's
inventory and prints the console digest; ``--stdout`` prints the full
markdown instead of writing files. (The former per-family
``blueprint_status.*`` reports are superseded by this one; any old
files at the database root are left in place.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stellariso.database.scan import (
    render_markdown,
    render_summary,
    report_json,
    scan_database,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("database", type=Path, help="database root")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the full markdown report instead of writing files",
    )
    parser.add_argument(
        "--families",
        nargs="*",
        default=None,
        help="scan only these families (default: every registered family)",
    )
    args = parser.parse_args(argv)

    if not args.database.is_dir():
        print(f"error: {args.database} is not a database directory", file=sys.stderr)
        return 2

    report = scan_database(args.database, families=args.families)
    if args.stdout:
        print(render_markdown(report), end="")
    else:
        markdown_path = args.database / "db_status.md"
        markdown_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
        json_path = args.database / "db_status.json"
        json_path.write_text(
            json.dumps(report_json(report), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(render_summary(report))
        print(f"wrote {markdown_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
