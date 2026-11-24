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

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

import requests

from stellariso.database.core import (
    Database,
    _count_data_files,
    _safe_extract,
    open_database,
)
from stellariso.database.design import (
    FamilyAdapter,
    ProductDesign,
    adapter_families,
    adapter_for,
)
from stellariso.database.inventory import write_inventory
from stellariso.database.manifest import read_manifest, strip_legacy, write_manifest
from stellariso.database.scan import ProductScan, scan_database
from stellariso.database.signature_cache import SignatureCache

__all__ = ["build_database"]


@dataclass
class _BuildKit:
    """One family's run resources of a build pass: the HTTP session and
    the reusable fetch handle, the signature cache the fetched parts'
    recorded hashes land in, and the politeness pause between form
    submissions."""

    session: requests.Session | None
    client: Any
    cache: SignatureCache | None
    form_pause: float


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


def _designed_bytes(
    adapter: FamilyAdapter, committed: list[ProductDesign]
) -> int | None:
    """The total designed download size of a package family, summed part
    by part through the adapter's own cost interface (:meth:`fetch_cost`).

    The design ``facts`` are family-private and carry sizes at whatever
    level the source publishes them (MIST: one archive per product,
    recorded top-level; Padova: per catalog file); ``fetch_cost`` is the
    one normalized view over both, so the dry-run summary asks it rather
    than reaching into the facts. ``None`` when any part's size is
    unknown — the summary then says so instead of undercounting.
    """
    total = 0
    for design in committed:
        for part in design.parts:
            size = adapter.fetch_cost(design, part).get("size_bytes")
            if size is None:
                return None
            total += size
    return total


def _complete_product(
    root: Path,
    adapter: FamilyAdapter,
    scan: ProductScan,
    kit: _BuildKit,
    *,
    extract: bool,
    log: Callable[[str], None],
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
        entry = adapter.fetch_part(
            design, part, directory, session=kit.session, client=kit.client, log=log
        )
        parts[part.name] = entry
        if kit.cache is not None:
            # the fetch already hashed the part: record the answer, so
            # the next scan classifies the fresh file without a re-read
            kit.cache.remember(directory / entry["file"], entry["sha256"])
        fetched = True
        if _is_submit_family(adapter):
            time.sleep(kit.form_pause)
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


def _scan_cache(
    root: Path, cache: bool | SignatureCache, *, writable: bool
) -> SignatureCache | None:
    """The cache one build mode scans with: ``True`` — the root's own
    cache, writable or not (a dry-run must touch nothing); ``False`` —
    none (every check a full read); an instance — as given, the
    caller's writability ruling."""
    if cache is True:
        return SignatureCache(root, writable=writable)
    if cache is False or cache is None:
        return None
    return cache


def _dry_run(
    root: Path,
    families: list[str],
    log: Callable[[str], None],
    *,
    cache: SignatureCache | None = None,
) -> None:
    report = scan_database(root, families=families, cache=cache)
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
            total = _designed_bytes(adapter, committed)
            size_text = (
                f"{total:,} bytes total ({total / 1e9:.1f} GB)"
                if total is not None
                else "size unknown from the design facts"
            )
            log(f"{family}: {len(committed)} package product(s), {size_text}")


def build_database(
    database: str | Path,
    models: Iterable[str] | None = None,
    *,
    session: requests.Session | None = None,
    cache: bool | SignatureCache = True,
    dry_run: bool = False,
    extract: bool = True,
    form_pause: float = 5.0,
    log: Callable[[str], None] = print,
) -> Database:
    """Build (or complete) a local database to every family's committed
    fetch stage (a staged source commits to a subset of its declared
    design; the scan still measures the whole design, so the gap stays
    visible in the two-state report).

    ``models`` limits the build to the given families (default: all).
    ``dry_run=True`` reports the plan — missing parts of clean products
    per family, with the manual-review list separate — and touches
    nothing (its scan serves the signature cache's recorded answers but
    never writes the cache file). ``session`` is used as given for every
    family; otherwise each family's own default session applies (a
    declared CA bundle is honored). Verification is never skippable:
    every recorded sha256 is checked on every run, and every
    content-based conformance check runs. ``cache`` controls only
    whether the file-derived answers (hashes, content facts) are served
    from the database's quick-signature cache instead of being re-derived
    by a full read — ``True`` (the default) uses the root's
    ``signature_cache.json`` (one ``stat`` per unchanged file;
    :mod:`~stellariso.database.signature_cache` for the whole contract,
    including the delete-to-re-verify rule), ``False`` bypasses it so
    every check reads the file (the force-full-check mode), and an
    explicit :class:`SignatureCache` instance is used as given. With
    ``extract=False`` only the official archives are kept (the complete,
    self-contained backup); ``Database.grid`` extracts a product on
    first open, verifying the archive's sha256 first — the right mode
    when the disk cannot hold the extracted form of every package at
    once. The archive always stays alongside any extraction.
    ``form_pause`` seconds are waited after every form submission (the
    service is a small public host; the default keeps submissions
    polite).
    """
    root = Path(database)
    families = _family_order(
        list(models) if models is not None else list(adapter_families())
    )

    if dry_run:
        _dry_run(root, families, log, cache=_scan_cache(root, cache, writable=False))
        return None

    root.mkdir(parents=True, exist_ok=True)
    scan_cache = _scan_cache(root, cache, writable=True)
    report = scan_database(root, families=families, cache=scan_cache)

    for family in families:
        adapter = adapter_for(family)
        fam = report.families[family]
        fam_session = session if session is not None else adapter.default_session(root)
        kit = _BuildKit(
            session=fam_session,
            client=adapter.fetch_client(session=fam_session),
            cache=scan_cache,
            form_pause=form_pause,
        )
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
            _complete_product(root, adapter, scan, kit, extract=extract, log=log)
            log(f"fetched {scan.design.relative_dir}")

    if scan_cache is not None:
        scan_cache.save_if_dirty()
    write_inventory(root)
    return open_database(root)
