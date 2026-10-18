"""The universal acquisition loop: complete every committed design.

One loop serves every family. It scans first (the two-state scanner),
then, product by product:

- a product needing review (any nonconforming part, or a directory at
  the designed path that maps elsewhere) is skipped with a NOTICE — a
  checksum proves integrity, not design membership, and whether such
  data is re-fetched is a human decision the status report carries;
- every missing part of a clean product is fetched through the family
  adapter (a package download, or one form submission with a polite
  pause in between);
- the product's MANIFEST is rewritten as clean v2 — kept parts carry
  over untouched, fetched parts are added, and the family's own section
  and identity fields come from the adapter;
- package products are extracted when the builder is asked to (the
  archive itself always stays; ``Database.grid`` also extracts on
  demand, verifying the recorded sha256 first).

Archived data is never overwritten and never deleted: the loop only
adds what is missing — re-running ``build_database`` completes whatever
is missing and keeps everything already verified.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

from stellariso.database.core import _count_data_files, _safe_extract, open_database
from stellariso.database.design import (
    FamilyAdapter,
    ProductDesign,
    adapter_for,
    adapter_families,
)
from stellariso.database.inventory import write_inventory
from stellariso.database.manifest import read_manifest, strip_legacy, write_manifest
from stellariso.database.scan import ProductScan, scan_database

__all__ = ["build_database"]


def _is_submit_family(adapter: FamilyAdapter) -> bool:
    for design in adapter.committed():
        for part in design.parts:
            return adapter.fetch_cost(design, part)["kind"] == "submit"
    return False


def _family_order(families: Iterable[str]) -> list[str]:
    """Package families first, form families last (downloads up front,
    the polite submission pacing afterwards)."""
    ordered = list(families)
    submits = [f for f in ordered if _is_submit_family(adapter_for(f))]
    return [f for f in ordered if f not in submits] + submits


def _complete_product(
    root: Path,
    adapter: FamilyAdapter,
    scan: ProductScan,
    *,
    session=None,
    client=None,
    extract: bool,
    form_pause: float,
    log,
) -> None:
    """Fetch the missing parts of one clean product and write its v2
    MANIFEST (kept parts carry over untouched)."""
    design = scan.design
    directory = root / design.relative_dir
    directory.mkdir(parents=True, exist_ok=True)
    manifest = (
        read_manifest(directory / "MANIFEST.json")
        if (directory / "MANIFEST.json").exists()
        else {}
    )
    parts = dict(manifest.get("parts") or {})
    fetched = False
    for part in design.parts:
        if part.name not in scan.missing_parts:
            continue
        parts[part.name] = adapter.fetch_part(
            design, part, directory, session=session, client=client, log=log
        )
        fetched = True
        if _is_submit_family(adapter):
            time.sleep(form_pause)
    if adapter.extracts:
        n_data_files = _count_data_files(directory)
        if extract and (fetched or n_data_files == 0) and parts:
            for archive in sorted(directory.iterdir()):
                if archive.is_file() and archive.suffix.lower() in (".txz", ".zip", ".tar"):
                    _safe_extract(archive, directory)
            n_data_files = _count_data_files(directory)
        manifest["n_data_files"] = n_data_files
        manifest["extracted"] = n_data_files > 0
    manifest["parts"] = parts
    payload = strip_legacy(dict(manifest))
    payload.update(
        {
            "family": design.family,
            "release": design.release,
            "label": design.label,
            "kind": design.kind,
        }
    )
    payload.update(adapter.manifest_fields(design))
    section = adapter.family_section(design)
    if section is not None:
        payload["family_section"] = section
    write_manifest(directory / "MANIFEST.json", payload)


def _dry_run(root: Path, families: list[str], log) -> None:
    report = scan_database(root, families=families)
    for family in families:
        adapter = adapter_for(family)
        fam = report.families[family]
        fetches = fam.auto_fetches()
        submit = _is_submit_family(adapter)
        # per-product missing lines: always for package families, and for
        # form families once their root exists (a measured database — a
        # fresh one would list every pending cell)
        if fetches and (not submit or (root / family).is_dir()):
            by_design: dict[str, list[str]] = {}
            for scan, part_name in fetches:
                by_design.setdefault(scan.design.relative_dir, []).append(part_name)
            for rel in sorted(by_design):
                log(f"{rel}: {', '.join(sorted(by_design[rel]))} missing")
        review = fam.review_products()
        if review:
            log(
                f"{family}: {len(review)} product(s) NOT in the automatic plan "
                "(manual review; never auto-refetched):"
            )
            for scan in review:
                log(f"  {scan.design.relative_dir}: {scan.detail()}")
        if submit:
            designed_count = fam.designed_count
            log(
                f"{family}: {len(fam.committed_keys)} fetch-stage cells "
                f"({designed_count:,} designed), {len(fetches)} form submissions "
                "to the fetch-stage target"
            )
        else:
            committed = list(adapter.committed())
            total = sum(d.facts.get("size_bytes") or 0 for d in committed)
            log(
                f"{family}: {len(committed)} package product(s), {total:,} bytes "
                f"total ({total / 1e9:.1f} GB)"
            )


def build_database(
    database: str | Path,
    models: Iterable[str] | None = None,
    session=None,
    verify_existing: bool = True,
    dry_run: bool = False,
    extract: bool = True,
    form_pause: float = 5.0,
    log=print,
):
    """Build (or complete) a local database with every family's design.

    ``models`` limits the build to the given families (default: all).
    ``dry_run=True`` reports the plan — missing parts of clean products
    per family, with the manual-review list separate — and touches
    nothing. ``session`` is used as given for every family; otherwise
    each family's own default session applies (a declared CA bundle is
    honored). ``verify_existing=False`` classifies present files without
    re-hashing them (the rebuild-trust knob). With ``extract=False``
    only the official archives are kept (the complete, self-contained
    backup); ``Database.grid`` extracts a product on first open,
    verifying the archive's sha256 first — the right mode when the disk
    cannot hold the extracted form of every package at once. The
    archive always stays alongside any extraction. ``form_pause``
    seconds are waited after every form submission (the service is a
    small public host; the default keeps submissions polite).
    """
    root = Path(database)
    families = _family_order(
        list(models) if models is not None else list(adapter_families())
    )

    if dry_run:
        _dry_run(root, families, log)
        return None

    root.mkdir(parents=True, exist_ok=True)
    report = scan_database(root, families=families, verify_checksums=verify_existing)

    for family in families:
        adapter = adapter_for(family)
        fam = report.families[family]
        fam_session = session if session is not None else adapter.default_session(root)
        client = adapter.fetch_client(session=fam_session)
        for key in sorted(fam.products):
            if key not in fam.committed_keys:
                continue  # beyond the committed target: never fetched
            scan = fam.products[key]
            if scan.needs_review:
                log(
                    f"NOTICE {scan.design.relative_dir}: {scan.detail()}; "
                    "product left untouched (manual review)"
                )
                continue
            if not scan.missing_parts:
                log(f"keep verified {scan.design.relative_dir}")
                continue
            _complete_product(
                root,
                adapter,
                scan,
                session=fam_session,
                client=client,
                extract=extract,
                form_pause=form_pause,
                log=log,
            )
            log(f"fetched {scan.design.relative_dir}")

    write_inventory(root)
    return open_database(root)
