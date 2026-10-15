"""Report blueprint completion for a stellariso PARSEC database.

Compares the form-computed products a database actually holds against
the declared acquisition blueprint
(stellariso.models.parsec.blueprint; docs/parsec/blueprint.md) and
writes the completion checklist: per set the full grid declaration
(parameter, range, step, count), per cell whether it is complete,
log-only, re-fetch-marked, or pending, plus the superseded directories
and any payload-completeness gaps. The report is the review artifact —
marked data is never deleted or refetched by this tool.

    python tools/parsec/blueprint_status.py C:/Users/me/stellariso-database

Writes ``blueprint_status.md`` and ``blueprint_status.json`` next to the
database's inventory and prints the console digest; ``--stdout`` prints
the full markdown instead of writing files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stellariso.models.parsec import blueprint
from stellariso.models.parsec.blueprint_status import (
    render_markdown,
    render_summary,
    scan_database,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("database", type=Path, help="database root (holds database.json)")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the full markdown report instead of writing files",
    )
    args = parser.parse_args(argv)

    if not (args.database / "database.json").exists():
        print(f"error: {args.database} carries no database.json — not a database root", file=sys.stderr)
        return 2

    report = scan_database(args.database)
    if args.stdout:
        print(render_markdown(report), end="")
    else:
        markdown_path = args.database / "blueprint_status.md"
        markdown_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
        machine = {
            "database": str(report.database),
            "generated_at": report.generated_at,
            "tier_totals": report.tier_totals(),
            "jobs_to_target": report.jobs_to_target(),
            "sets": {
                key: {
                    "tier": ts.tier,
                    "mh_values": list(ts.mh_values),
                    "omega_values": list(ts.omega_values),
                    "eta_values": list(ts.eta_values),
                    "fetch_eta_values": list(ts.fetch_eta_values),
                    "n_intpc_values": list(ts.n_intpc_values),
                    "dust_m_values": list(ts.dust_m_values),
                    "dust_c_values": list(ts.dust_c_values),
                    "lpv_values": list(ts.lpv_values),
                    "designed_cells": len(report.cells[key]),
                    "counts_over_fetch_target": report.counts(key),
                    # archived (non-pending) cells only: the full design
                    # spans tens of thousands of still-pending cells
                    "archived_cells": {
                        label: {"status": scan.status, "reasons": scan.reasons}
                        for label, scan in sorted(report.cells[key].items())
                        if scan.status != "pending"
                    },
                }
                for key, ts in blueprint.TRACK_SETS.items()
            },
            "superseded": report.superseded,
            "payload_gaps": report.payload_gaps,
        }
        json_path = args.database / "blueprint_status.json"
        json_path.write_text(
            json.dumps(machine, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(render_summary(report))
        print(f"wrote {markdown_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
