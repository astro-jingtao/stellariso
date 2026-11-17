"""Build (or complete) a local stellariso database, from the CLI.

Command-line form of ``stellariso.build_database``: every family's
committed fetch stage is acquired — published packages are downloaded
from the URLs the release catalogs record (MIST, Padova), and
form-computed products are submitted through the source's official
computation service (PARSEC's CMD web form). For the package families
the committed stage is the whole declared design; a staged source
commits to a declared subset of its blueprint (PARSEC), and the cells
beyond it are designed but never fetched. ``db_status.py`` measures a
database against the full declared design, so the gap between the
blueprint and the fetched content stays visible. Re-running completes
whatever is missing; already verified products are never re-fetched
or re-computed.

    python tools/database/build_database.py /path/to/database --dry-run
    python tools/database/build_database.py /path/to/database --families padova
"""

from __future__ import annotations

import argparse
from pathlib import Path

import stellariso


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "database", type=Path, help="database root (created when absent)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the plan (missing parts per family) and touch nothing",
    )
    parser.add_argument(
        "--families",
        nargs="+",
        help="limit the build to these families (default: all)",
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="keep only the official archives; Database.grid extracts a "
        "product on first open (the disk-saving mode)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="classify present files without re-hashing them "
        "(the rebuild-trust knob)",
    )
    parser.add_argument(
        "--form-pause",
        type=float,
        default=5.0,
        help="seconds waited after every form submission (default 5.0; "
        "the service is a small public host)",
    )
    args = parser.parse_args(argv)

    stellariso.build_database(
        args.database,
        models=args.families,
        dry_run=args.dry_run,
        extract=not args.no_extract,
        verify_existing=not args.skip_verify,
        form_pause=args.form_pause,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
