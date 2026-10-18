"""Transfer and maintain a stellariso database between machines.

Subcommands (stage-by-stage; this tool grows with the transfer work):

- ``migrate-manifests <db> [--apply]`` — rewrite every product MANIFEST
  of a database to clean schema stellariso-manifest/2. One atomic
  rewrite per product; archived data files are not touched. Without
  ``--apply`` the migration is a dry run listing what would change.
  Manifests that cannot be upgraded losslessly are reported with their
  reasons and left untouched (the read bridge keeps them usable);
  their disposition stays with the database owner.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stellariso.database.manifest import upgrade_manifests


def _cmd_migrate_manifests(args) -> int:
    if not args.database.is_dir():
        print(f"error: {args.database} is not a database directory", file=sys.stderr)
        return 2
    report = upgrade_manifests(args.database, dry_run=not args.apply, log=print)
    mode = "applied" if args.apply else "dry run (nothing written; pass --apply)"
    print(
        f"{mode}: {len(report.upgraded)} manifest(s) "
        f"{'' if args.apply else 'would be '}upgraded to v2, "
        f"{len(report.already_current)} already current, "
        f"{len(report.failed)} refused"
    )
    if report.failed:
        print("refused (left untouched, still readable through the bridge):")
        for failure in report.failed:
            print(f"  {failure.directory}: {'; '.join(failure.reasons)}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser(
        "migrate-manifests", help="rewrite every MANIFEST to clean v2"
    )
    migrate.add_argument("database", type=Path, help="database root")
    migrate.add_argument(
        "--apply", action="store_true", help="write (default is a dry run)"
    )
    migrate.set_defaults(func=_cmd_migrate_manifests)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
