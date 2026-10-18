"""Transfer and maintain a stellariso database between machines.

Subcommands:

- ``export <db>`` — write a declarative selection of the database to
  ``<db>/export/<name>/`` (transfer.json, files.rsync, files.txt, and a
  receiving README). Selection flags: --families, --collections,
  --labels, --products, --states (default complete), --target-only,
  and the PARSEC axis filters (--mh, --omega, --eta, --n-intpc,
  --dust-m, --dust-c, --lpv, --tier). ``--checksums all`` hashes the
  unrecorded files (extracted content) too.
- ``rsync <db> --name N --destination user@host:/path`` — assemble the
  rsync transport for one export; ``--exec`` runs it.
- ``merge <source> <target>`` — import one local database (or partial
  copy) into another through the copy channel; same selection flags,
  everything sound by default.
- ``verify <db> --plan <path>`` — check a database against an export
  plan (every recorded sha recomputed).
- ``refresh <db>`` — regenerate database.json, README.md,
  unified-parameters.md, and db_status.* from the product directories.
- ``migrate-manifests <db> [--apply]`` — rewrite every product MANIFEST
  to clean schema stellariso-manifest/2 (dry run by default; refused
  manifests are reported, never forced).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stellariso.database.manifest import upgrade_manifests


def _parse_axis_values(text: str):
    """'a,b,c' -> ('a','b','c'); a single value stays a scalar."""
    if "," in text:
        return tuple(text.split(","))
    return text


def _parse_criteria(args, *, default_states):
    from stellariso.database.design import SelectionCriteria

    states = tuple(args.states) if args.states else default_states
    axes = {}
    if getattr(args, "mh", None):
        text = args.mh
        if ":" in text:
            lo, hi = text.split(":", 1)
            axes["mh"] = (float(lo), float(hi))
        else:
            axes["mh"] = tuple(float(v) for v in text.split(","))
    for flag, axis, cast in (
        ("omega", "omega", float),
        ("eta", "eta", float),
        ("n_intpc", "n_inTPC", int),
        ("dust_m", "dust_m", str),
        ("dust_c", "dust_c", str),
        ("lpv", "lpv", str),
        ("tier", "tier", str),
    ):
        value = getattr(args, flag, None)
        if value:
            parsed = _parse_axis_values(value)
            axes[axis] = (
                tuple(cast(v) for v in parsed) if isinstance(parsed, tuple) else cast(parsed)
            )
    return SelectionCriteria(
        families=tuple(args.families) if args.families else None,
        collections=tuple(args.collections) if args.collections else None,
        labels=tuple(args.labels) if args.labels else None,
        products=tuple(args.products) if args.products else None,
        states=states,
        target_only=args.target_only,
        axes=axes,
    )


def _add_selection_flags(parser, states_default):
    parser.add_argument("--families", nargs="*", default=None)
    parser.add_argument("--collections", nargs="*", default=None)
    parser.add_argument("--labels", nargs="*", default=None)
    parser.add_argument(
        "--products",
        nargs="*",
        default=None,
        help="explicit family/collection/label paths",
    )
    parser.add_argument("--states", nargs="*", default=None)
    parser.set_defaults(states_default=states_default)
    parser.add_argument("--target-only", action="store_true")
    parser.add_argument(
        "--mh", default=None, help="[M/H] window 'lo:hi' or a comma list"
    )
    parser.add_argument("--omega", default=None)
    parser.add_argument("--eta", default=None)
    parser.add_argument("--n-intpc", default=None)
    parser.add_argument("--dust-m", default=None)
    parser.add_argument("--dust-c", default=None)
    parser.add_argument("--lpv", default=None)
    parser.add_argument("--tier", default=None)


def _cmd_export(args) -> int:
    from stellariso.database.transfer import export_database

    criteria = _parse_criteria(args, default_states=("complete",))
    try:
        result = export_database(
            args.database, criteria, name=args.name, checksums=args.checksums
        )
    except (FileExistsError, NotADirectoryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"wrote {result.outdir / 'transfer.json'} "
        f"({result.products} products, "
        f"{result.plan['totals']['files']} files, "
        f"{result.plan['totals']['bytes']:,} bytes)"
    )
    return 0


def _cmd_rsync(args) -> int:
    from stellariso.database.transfer import rsync_command, run_rsync

    export_dir = args.database / "export" / args.name
    if not (export_dir / "files.rsync").is_file():
        print(f"error: {export_dir} carries no files.rsync — export first", file=sys.stderr)
        return 2
    print(rsync_command(args.database, export_dir, args.destination))
    if args.exec:
        try:
            run_rsync(args.database, export_dir, args.destination)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
    return 0


def _cmd_merge(args) -> int:
    from stellariso.database.transfer import merge_database

    criteria = _parse_criteria(args, default_states=("complete", "incomplete"))
    try:
        report = merge_database(args.source, args.target, criteria)
    except (NotADirectoryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report.summary())
    return 0 if not report.conflicts else 1


def _cmd_verify(args) -> int:
    from stellariso.database.transfer import verify_transfer

    try:
        report = verify_transfer(args.database, args.plan)
    except (NotADirectoryError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report.summary())
    for rel in report.missing:
        print(f"  missing: {rel}")
    for rel in report.size_mismatches:
        print(f"  size mismatch: {rel}")
    for rel in report.sha_mismatches:
        print(f"  sha mismatch: {rel}")
    return 0 if report.ok else 1


def _cmd_refresh(args) -> int:
    from stellariso.database.inventory import refresh_database

    try:
        refresh_database(args.database)
    except NotADirectoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


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

    export = sub.add_parser("export", help="write a selection to <db>/export/<name>/")
    export.add_argument("database", type=Path, help="database root")
    export.add_argument("--name", default="selection", help="export directory name")
    export.add_argument(
        "--checksums", choices=("recorded", "all"), default="recorded"
    )
    _add_selection_flags(export, ("complete",))
    export.set_defaults(func=_cmd_export)

    rsync = sub.add_parser("rsync", help="assemble (or run) the rsync transport")
    rsync.add_argument("database", type=Path, help="database root")
    rsync.add_argument("--name", default="selection", help="export directory name")
    rsync.add_argument("--destination", required=True, help="user@host:/path/to/db/")
    rsync.add_argument("--exec", action="store_true", help="run the command")
    rsync.set_defaults(func=_cmd_rsync)

    merge = sub.add_parser("merge", help="import one database into another")
    merge.add_argument("source", type=Path, help="source database root")
    merge.add_argument("target", type=Path, help="target database root")
    _add_selection_flags(merge, ("complete", "incomplete"))
    merge.set_defaults(func=_cmd_merge)

    verify = sub.add_parser("verify", help="check a database against an export plan")
    verify.add_argument("database", type=Path, help="database root")
    verify.add_argument("--plan", type=Path, required=True, help="transfer.json path")
    verify.set_defaults(func=_cmd_verify)

    refresh = sub.add_parser("refresh", help="regenerate the database-root artifacts")
    refresh.add_argument("database", type=Path, help="database root")
    refresh.set_defaults(func=_cmd_refresh)

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
