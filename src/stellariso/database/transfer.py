"""Transfer: merge databases, export selections, verify, move with rsync.

Invariants every path here obeys (they hold for the builder too):

1. Archived data is never overwritten and never deleted; a merge only
   adds what is missing.
2. A product holding any nonconforming part is never auto-completed by
   a merge, on either side: the source's disowned parts do not
   propagate, and a target needing review is left untouched (a
   checksum proves integrity, not design membership).
3. A conflicting part (both sides archived, shas disagree) is never
   resolved automatically: both values are recorded and a human
   decides.
4. Root-level derived artifacts (database.json, README, db_status) are
   regenerated from the merged directories, never copied or merged.

``merge_database`` imports one local database (or any partial copy of
one — an rsync'd subset is itself a legal database) into another, keyed
by directory relative path with the manifest identity triple
cross-checked. ``export_database`` writes a declarative selection to
``<db>/export/<name>/`` — the machine-readable ``transfer.json``
carrying every file of every selected product with its recorded sha
(extracted content included; extraction is local materialization state,
never a completeness condition), the ``files.rsync`` and ``files.txt``
path tables, and a README with the receiving procedure. ``verify``
recomputes every recorded checksum; ``rsync_command`` assembles (and
optionally runs) the transport itself.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from stellariso.database.design import SelectionCriteria, adapter_for
from stellariso.database.inventory import refresh_database
from stellariso.database.manifest import read_manifest, write_manifest
from stellariso.database.scan import DatabaseReport, ProductScan, scan_database
from stellariso.integrity import sha256_file

__all__ = [
    "MergeConflict",
    "MergeReport",
    "merge_database",
    "ExportResult",
    "export_database",
    "VerifyReport",
    "verify_transfer",
    "rsync_command",
    "run_rsync",
]


def _selected(report: DatabaseReport, criteria: SelectionCriteria | None):
    """The located products of a scan a criteria selects."""
    for family in report.families.values():
        for key, scan in sorted(family.products.items()):
            if scan.directory is None:
                continue
            if criteria is not None:
                if not adapter_for(scan.design.family).matches_criteria(
                    scan.design, criteria
                ):
                    continue
                if scan.state not in criteria.states:
                    continue
                if criteria.target_only and key not in family.committed_keys:
                    continue
            yield family, key, scan


def _part_sha(manifest: dict, part_name: str) -> str | None:
    entry = (manifest.get("parts") or {}).get(part_name) or {}
    return entry.get("sha256")


# -- merge ----------------------------------------------------------------------


@dataclass(frozen=True)
class MergeConflict:
    product: str
    part: str
    source_sha: str | None
    target_sha: str | None


@dataclass
class MergeReport:
    """What one merge did, product by product."""

    source: Path
    target: Path
    merged_products: list[str] = field(default_factory=list)  # whole directories
    built_products: list[str] = field(default_factory=list)  # new dirs, ok parts only
    completed_parts: list[tuple[str, str]] = field(default_factory=list)
    kept_products: list[str] = field(default_factory=list)
    conflicts: list[MergeConflict] = field(default_factory=list)
    source_needs_review: list[str] = field(default_factory=list)
    target_needs_review: list[str] = field(default_factory=list)
    source_superseded: list[dict] = field(default_factory=list)
    identity_mismatches: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.merged_products or self.built_products or self.completed_parts)

    def summary(self) -> str:
        lines = [
            f"merge {self.source} -> {self.target}: "
            f"{len(self.merged_products)} product(s) merged whole, "
            f"{len(self.built_products)} built from sound parts, "
            f"{len(self.completed_parts)} part(s) completed into existing products, "
            f"{len(self.kept_products)} already present"
        ]
        lines.append(
            f"conflicts {len(self.conflicts)}; source review-skipped "
            f"{len(self.source_needs_review)}; target review-skipped "
            f"{len(self.target_needs_review)}; superseded not merged "
            f"{len(self.source_superseded)}; identity mismatches "
            f"{len(self.identity_mismatches)}"
        )
        for conflict in self.conflicts:
            lines.append(
                f"  conflict {conflict.product}/{conflict.part}: source "
                f"{conflict.source_sha} vs target {conflict.target_sha} "
                "(target untouched)"
            )
        return "\n".join(lines)


def _copy_part_file(source_dir: Path, target_dir: Path, filename: str) -> None:
    """Copy one file into place atomically (.part then replace)."""
    src = source_dir / filename
    if not src.exists():
        return
    dst = target_dir / filename
    tmp = dst.with_suffix(dst.suffix + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _merge_product(
    source_root: Path,
    target_root: Path,
    staging: Path,
    s_scan: ProductScan,
    t_scan: ProductScan | None,
    report: MergeReport,
    log,
) -> None:
    design = s_scan.design
    key = design.key
    rel = design.relative_dir
    s_manifest = read_manifest(s_scan.directory / "MANIFEST.json")

    ok_parts = [p for p in design.parts if s_scan.parts[p.name].kind == "ok"]
    if s_scan.blocked_reason or (not ok_parts and s_scan.nonconforming_parts):
        report.source_needs_review.append(key)
        log(f"skip {rel}: source needs review ({s_scan.detail()})")
        return
    if not ok_parts:
        report.source_needs_review.append(key)
        log(f"skip {rel}: no sound part to merge")
        return

    if t_scan is not None and t_scan.needs_review:
        report.target_needs_review.append(key)
        log(f"skip {rel}: target needs review, left untouched")
        return

    # conflicts: an overlapping part archived on both sides with
    # different shas voids the whole product for this merge
    if t_scan is not None:
        t_manifest = (
            read_manifest(t_scan.directory / "MANIFEST.json")
            if t_scan.directory is not None
            else {}
        )
        product_conflicts = []
        for part in ok_parts:
            t_verdict = t_scan.parts.get(part.name)
            if t_verdict is None or t_verdict.kind == "missing":
                continue
            s_sha = _part_sha(s_manifest, part.name)
            t_sha = _part_sha(t_manifest, part.name)
            if s_sha and t_sha and s_sha != t_sha:
                product_conflicts.append(MergeConflict(key, part.name, s_sha, t_sha))
        if product_conflicts:
            report.conflicts.extend(product_conflicts)
            log(f"skip {rel}: sha conflict (recorded; target untouched)")
            return

    target_dir = target_root / rel
    t_dir_exists = t_scan is not None and t_scan.directory is not None

    if not t_dir_exists:
        disowned = [p.name for p in design.parts if s_scan.parts[p.name].kind == "nonconforming"]
        if not disowned:
            # every archived part sound: staged whole-directory copy
            stage = staging / uuid.uuid4().hex
            stage.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(s_scan.directory, stage)
            staged_manifest = read_manifest(stage / "MANIFEST.json")
            identity = (
                staged_manifest.get("family"),
                staged_manifest.get("release"),
                staged_manifest.get("label"),
            )
            if identity != (design.family, design.release, design.label):
                report.identity_mismatches.append(key)
                log(
                    f"skip {rel}: staged manifest identity {identity} does not "
                    f"match the design"
                )
                return
            for part in ok_parts:
                recorded = _part_sha(staged_manifest, part.name)
                if recorded and sha256_file(stage / part.filename) != recorded:
                    raise ValueError(
                        f"staged copy of {rel}/{part.name} fails its recorded "
                        "sha256; merge aborted for this product"
                    )
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, target_dir)
            report.merged_products.append(key)
            log(f"merged {rel} (whole directory)")
            return
        # a mixed product merges its sound parts only; the disowned data
        # never propagates (the parts it leaves behind count as missing
        # and may be fetched fresh later)
        target_dir.mkdir(parents=True, exist_ok=True)
        for part in ok_parts:
            _copy_part_file(s_scan.directory, target_dir, part.filename)
            record = (s_manifest.get("parts") or {}).get(part.name, {}).get("record")
            if record:
                _copy_part_file(s_scan.directory, target_dir, record)
            recorded = _part_sha(s_manifest, part.name)
            if recorded and sha256_file(target_dir / part.filename) != recorded:
                raise ValueError(
                    f"copied part {rel}/{part.name} fails its recorded sha256; "
                    "merge aborted for this product"
                )
            report.completed_parts.append((key, part.name))
        payload = dict(s_manifest)
        payload["parts"] = {
            name: entry
            for name, entry in (s_manifest.get("parts") or {}).items()
            if name in {p.name for p in ok_parts}
        }
        write_manifest(target_dir / "MANIFEST.json", payload)
        report.built_products.append(key)
        log(f"built {rel} from sound parts (disowned parts not propagated)")
        return

    # the target directory exists: part-level completion of its misses
    t_manifest = read_manifest(target_dir / "MANIFEST.json")
    added = []
    for part in ok_parts:
        verdict = t_scan.parts.get(part.name)
        if verdict is None or verdict.kind != "missing":
            continue
        _copy_part_file(s_scan.directory, target_dir, part.filename)
        record = (s_manifest.get("parts") or {}).get(part.name, {}).get("record")
        if record:
            _copy_part_file(s_scan.directory, target_dir, record)
        recorded = _part_sha(s_manifest, part.name)
        if recorded and sha256_file(target_dir / part.filename) != recorded:
            raise ValueError(
                f"copied part {rel}/{part.name} fails its recorded sha256; "
                "merge aborted for this product"
            )
        added.append(part.name)
        report.completed_parts.append((key, part.name))
    if added:
        parts = dict(t_manifest.get("parts") or {})
        for name in added:
            parts[name] = (s_manifest.get("parts") or {}).get(name)
        payload = dict(t_manifest)
        payload["parts"] = parts
        if "family_section" not in payload and s_manifest.get("family_section"):
            payload["family_section"] = s_manifest["family_section"]
        write_manifest(target_dir / "MANIFEST.json", payload)
        log(f"completed {rel}: {', '.join(added)}")
    else:
        report.kept_products.append(key)


def merge_database(
    source: str | Path,
    target: str | Path,
    criteria: SelectionCriteria | None = None,
    *,
    log=print,
) -> MergeReport:
    """Import one local database (or partial copy) into another.

    Never overwrites, never deletes: whole sound products land as
    staged atomic directory copies, sound parts of mixed products
    complete matching products part by part, everything already
    present stays. Conflicts and review cases are recorded, not
    resolved. Derived root artifacts are regenerated afterwards.
    """
    source = Path(source)
    target = Path(target)
    if not source.is_dir():
        raise NotADirectoryError(f"{source} is not a database directory")
    if source.resolve() == target.resolve():
        raise ValueError("source and target are the same database")
    target.mkdir(parents=True, exist_ok=True)

    staging = target / ".staging"
    if staging.exists():
        shutil.rmtree(staging)  # sweep leftovers of an interrupted run
    staging.mkdir(parents=True, exist_ok=True)

    source_report = scan_database(source)
    target_report = scan_database(target)
    report = MergeReport(source=source, target=target)
    report.source_superseded = source_report.all_superseded()
    t_index = {
        (family.family, key): scan
        for family in target_report.families.values()
        for key, scan in family.products.items()
    }

    try:
        for family, key, s_scan in _selected(source_report, criteria):
            _merge_product(
                source,
                target,
                staging,
                s_scan,
                t_index.get((family.family, key)),
                report,
                log,
            )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    refresh_database(target, log=log)
    return report


# -- export ----------------------------------------------------------------------


@dataclass
class ExportResult:
    """One written export plan."""

    database: Path
    outdir: Path
    plan: dict

    @property
    def products(self) -> int:
        return len(self.plan["products"])


def _recorded_shas(scan: ProductScan) -> dict[str, str]:
    from stellariso.exceptions import ManifestError

    try:
        manifest = read_manifest(scan.directory / "MANIFEST.json")
    except ManifestError:
        return {}
    out = {}
    for entry in (manifest.get("parts") or {}).values():
        if isinstance(entry, dict) and entry.get("file") and entry.get("sha256"):
            out[entry["file"]] = entry["sha256"]
    return out


def export_database(
    database: str | Path,
    criteria: SelectionCriteria | None = None,
    name: str = "selection",
    *,
    checksums: str = "recorded",
    log=print,
) -> ExportResult:
    """Write a selection of one database to ``<db>/export/<name>/``.

    The export travels with the database (rsync from the database root
    carries it along). Every file of every selected product is listed —
    archives, computed tables, records, and extracted content alike:
    extraction is local materialization state and never a selection or
    completeness condition. Shas come from the MANIFESTs as recorded;
    ``checksums="all"`` hashes the unrecorded files too (the extracted
    content), making the plan end-to-end verifiable at the cost of
    reading every selected byte.
    """
    from stellariso import __version__
    from stellariso.database.manifest import utc_now_iso

    root = Path(database)
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a database directory")
    criteria = criteria or SelectionCriteria()
    report = scan_database(root)
    outdir = root / "export" / name
    if outdir.exists():
        raise FileExistsError(
            f"{outdir} already exists; choose another --name or remove it"
        )

    entries = []
    total_bytes = 0
    total_files = 0
    for family, key, scan in _selected(report, criteria):
        recorded = _recorded_shas(scan)
        files = []
        for path in sorted(scan.directory.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            sha = recorded.get(path.name)
            if sha is None and checksums == "all":
                sha = sha256_file(path)
            files.append(
                {"path": rel, "size_bytes": path.stat().st_size, "sha256": sha}
            )
            total_bytes += path.stat().st_size
            total_files += 1
        section = adapter_for(scan.design.family).family_section(scan.design) or {}
        entries.append(
            {
                "family": scan.design.family,
                "collection": scan.design.collection,
                "release": scan.design.release,
                "label": scan.design.label,
                "kind": scan.design.kind,
                "state": scan.state,
                **({"axes": section["axes"]} if section.get("axes") else {}),
                "files": files,
            }
        )

    plan = {
        "stellariso_version": __version__,
        "generated_at": utc_now_iso(),
        "selection": criteria.describe(),
        "products": entries,
        "totals": {
            "products": len(entries),
            "files": total_files,
            "bytes": total_bytes,
            "files_without_sha": sum(
                1 for e in entries for f in e["files"] if f["sha256"] is None
            ),
        },
    }

    outdir.mkdir(parents=True)
    plan_rel_dir = f"export/{name}"
    (outdir / "transfer.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    rsync_lines = [e["family"] + "/" + e["collection"] + "/" + e["label"] for e in entries]
    rsync_lines.append(f"{plan_rel_dir}/transfer.json")
    (outdir / "files.rsync").write_text(
        "\n".join(rsync_lines) + "\n", encoding="utf-8", newline="\n"
    )
    txt_lines = [f["path"] for e in entries for f in e["files"]]
    txt_lines.append(f"{plan_rel_dir}/transfer.json")
    (outdir / "files.txt").write_text(
        "\n".join(txt_lines) + "\n", encoding="utf-8", newline="\n"
    )
    (outdir / "README.md").write_text(
        _export_readme(root, name, plan),
        encoding="utf-8",
        newline="\n",
    )
    log(
        f"exported {len(entries)} product(s), {total_files} file(s), "
        f"{total_bytes:,} bytes to {outdir}"
    )
    return ExportResult(database=root, outdir=outdir, plan=plan)


def _export_readme(root: Path, name: str, plan: dict) -> str:
    return (
        f"# stellariso database transfer: {name}\n"
        "\n"
        f"Selection: {plan['selection']}. "
        f"{plan['totals']['products']} product(s), "
        f"{plan['totals']['files']} file(s), {plan['totals']['bytes']:,} bytes.\n"
        "\n"
        "## Sending\n"
        "\n"
        "```bash\n"
        f"rsync -a --info=progress2 --files-from={root / 'export' / name / 'files.rsync'} "
        f"{root}/ user@host:/path/to/target-db/\n"
        "```\n"
        "\n"
        "Without rsync (Windows): copy every path listed in files.txt from a "
        "matching tree, or use the merge channel "
        "(stellariso.merge_database(source, target)).\n"
        "\n"
        "## Receiving\n"
        "\n"
        "1. the data lands under the target database root (any subset of "
        "product directories is itself a legal database);\n"
        "2. verify: `python tools/db_transfer.py verify <target-db> "
        f"--plan <target-db>/export/{name}/transfer.json`;\n"
        "3. refresh: `python tools/db_transfer.py refresh <target-db>` "
        "(regenerates database.json, README.md, unified-parameters.md, "
        "db_status.*).\n"
    )


# -- verify ---------------------------------------------------------------------


@dataclass
class VerifyReport:
    """The outcome of checking a database against an export plan."""

    database: Path
    plan_path: Path
    checked_files: int = 0
    missing: list[str] = field(default_factory=list)
    size_mismatches: list[str] = field(default_factory=list)
    sha_mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.size_mismatches or self.sha_mismatches)

    def summary(self) -> str:
        status = "OK" if self.ok else "FAILED"
        return (
            f"verify {self.database} against {self.plan_path}: {status} — "
            f"{self.checked_files} file(s) checked, {len(self.missing)} missing, "
            f"{len(self.size_mismatches)} size mismatches, "
            f"{len(self.sha_mismatches)} sha mismatches"
        )


def verify_transfer(database: str | Path, plan_path: str | Path) -> VerifyReport:
    """Check every recorded file of an export plan against a database.

    Files the plan carries a sha for are hashed; the rest (extracted
    content exported without ``checksums="all"``) are checked for
    presence and size.
    """
    root = Path(database)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    report = VerifyReport(database=root, plan_path=Path(plan_path))
    for entry in plan["products"]:
        for file_entry in entry["files"]:
            rel = file_entry["path"]
            path = root / rel
            report.checked_files += 1
            if not path.is_file():
                report.missing.append(rel)
                continue
            if file_entry["size_bytes"] != path.stat().st_size:
                report.size_mismatches.append(rel)
            if file_entry["sha256"] and sha256_file(path) != file_entry["sha256"]:
                report.sha_mismatches.append(rel)
    return report


# -- rsync -----------------------------------------------------------------------


def rsync_command(database: str | Path, export_dir: str | Path, destination: str) -> str:
    """The transport command for one export (assembled, not run)."""
    database = Path(database)
    export_dir = Path(export_dir)
    return (
        f"rsync -a --info=progress2 "
        f"--files-from={export_dir / 'files.rsync'} {database}/ {destination}"
    )


def run_rsync(
    database: str | Path, export_dir: str | Path, destination: str, *, log=print
) -> None:
    """Execute the rsync transport (the command above, run as-is)."""
    if shutil.which("rsync") is None:
        raise FileNotFoundError(
            "rsync is not on PATH; on Windows provide it through WSL or "
            "cwRsync, or use the copy channel (merge_database) instead"
        )
    database = Path(database)
    export_dir = Path(export_dir)
    command = [
        "rsync",
        "-a",
        "--info=progress2",
        f"--files-from={export_dir / 'files.rsync'}",
        f"{database}/",
        destination,
    ]
    log(" ".join(command))
    subprocess.run(command, check=True)
