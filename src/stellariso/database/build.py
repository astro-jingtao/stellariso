"""The database build loop (transitional: verbatim behavior of the
former stellariso/database.py build half).

Stage 2 of the unification replaces this module's loop with the
universal adapter-driven builder; it lives here meanwhile so the
package split of stage 1 changes no build behavior. The read side
(core), the manifest handling (manifest), and the scanner (scan) are
already the new modules.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

from stellariso.database.core import _count_data_files, _safe_extract, open_database
from stellariso.database.inventory import write_inventory
from stellariso.exceptions import SourceUnavailableError
from stellariso.integrity import sha256_file
from stellariso.models import catalog
from stellariso.registry import backend_names, references
from stellariso.warnings import CatalogSizeMismatchWarning

__all__ = ["build_database"]

_CHUNK = 1 << 20
_TIMEOUT_GET = 1800


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _download(url: str, target: Path, session: requests.Session) -> tuple[str, int]:
    digest = hashlib.sha256()
    tmp = target.with_suffix(target.suffix + ".part")
    with session.get(url, stream=True, timeout=_TIMEOUT_GET) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                fh.write(chunk)
                digest.update(chunk)
    tmp.replace(target)
    return digest.hexdigest(), target.stat().st_size


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    tmp.replace(path)


def _product_target(database: Path, family: str, release: str, label: str) -> Path:
    return database / family / release / label


def build_database(
    database: str | Path,
    models: Iterable[str] | None = None,
    session: requests.Session | None = None,
    verify_existing: bool = True,
    dry_run: bool = False,
    extract: bool = True,
    form_pause: float = 5.0,
):
    """Build (or complete) a local database with the full published matrix.

    Package products (every release and parameter set a source publishes
    as an official package) are downloaded, checksummed, extracted, and
    recorded in a per-product MANIFEST. Form products (a source whose
    only isochrone channel is an official computation service — the
    PARSEC CMD web form) are built from that source's declared
    acquisition blueprint: each fetch-stage cell submits its two age
    grids as separate jobs into one cell directory, verifies the
    server's header echo, and archives both tables with their complete
    acquisition records (exact payload, timestamps, sha256) and one
    extended cell MANIFEST. Products already present with a matching
    checksum are never re-acquired, whichever the channel — a form job
    is server-side compute, so re-running the build only completes what
    is missing. Cells whose archived log-age half does not conform to
    the design are skipped with a notice, never patched or overwritten
    (``tools/parsec/blueprint_status.py`` is the review artifact).

    ``models`` limits the build to the given families (default: all).
    ``dry_run=True`` only reports what would be fetched. With
    ``extract=False`` only the official archives are kept (the complete,
    self-contained backup); ``Database.grid`` extracts a product on first
    open, verifying the archive's sha256 first — the right mode when the
    disk cannot hold the extracted form of every package at once (the
    extracted size is several times the archive size). ``form_pause``
    seconds are waited between consecutive form jobs (the service is a
    small public host; the default keeps submissions polite).
    """
    root = Path(database)
    families = list(models) if models is not None else list(backend_names())

    catalogs = {family: catalog(family) for family in families}
    for family, cat in catalogs.items():
        if cat.get("channel") == "manual":
            _fail_manual(root, family, cat)
        if cat.get("channel") == "form":
            families = [f for f in families if f != family] + [family]

    jobs = []
    for family in families:
        cat = catalogs[family]
        if cat.get("channel") == "form":
            continue  # acquired through the blueprint below
        for release_entry in cat["releases"]:
            for product in release_entry["products"]:
                jobs.append((family, release_entry, product))

    if dry_run:
        total = 0
        missing_size = 0
        for family, release_entry, product in jobs:
            size = product.get("size_bytes")
            if size is None:
                missing_size += 1
                size_text = "size unknown"
            else:
                total += size
                size_text = f"{size:,} bytes"
            print(f"{family}/{release_entry['release']}/{product['label']}  {size_text}")
        print(
            f"{len(jobs)} package product(s), {total:,} bytes total "
            f"({total / 1e9:.1f} GB, {missing_size} with unknown size)"
        )
        for family, cat in catalogs.items():
            if cat.get("channel") == "form":
                from stellariso.models.parsec.build import fetch_plan

                plan = fetch_plan(root if root.exists() else None)
                print(
                    f"{family}: {plan['target_cells']} fetch-stage cells "
                    f"({sum(v['designed_cells'] for v in plan['sets'].values())} "
                    f"designed), {plan['submissions_to_target']} form submissions "
                    "to the fetch-stage target"
                )
        return None

    root.mkdir(parents=True, exist_ok=True)
    sessions = _sessions(root, families, session)

    for family, release_entry, product in jobs:
        _build_product(
            root, family, release_entry["release"], product,
            sessions[family], verify_existing, extract=extract,
        )

    for family, cat in catalogs.items():
        if cat.get("channel") == "form":
            from stellariso.models.parsec.build import build_blueprint

            build_blueprint(root, pause=form_pause)

    write_inventory(root)
    return open_database(root)


def _fail_manual(database: Path, family: str, cat: dict) -> None:
    raise SourceUnavailableError(
        f"{family} publishes no downloadable packages: {cat.get('manual_note', '')} "
        f"(full procedure: docs/data-sources.md). Obtain the files, put them "
        f"under {database / family}, and create their MANIFESTs with "
        "stellariso.register_local_product()."
    )


def _default_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "stellariso (isochrone database builder)"
    return s


def _sessions(
    database: Path, families: list[str], session: requests.Session | None
) -> dict[str, requests.Session]:
    """One session per family: an explicit session is used as given; default
    sessions honor a family's declared CA bundle (hosts whose TLS chain
    omits an intermediate — currently stev.oapd.inaf.it — get the bundled
    intermediate appended to the standard trust store, so verification
    stays ON instead of being switched off)."""
    if session is not None:
        return {family: session for family in families}

    sessions = {}
    for family in families:
        s = _default_session()
        bundle_name = catalog(family).get("ca_bundle")
        if bundle_name:
            s.verify = str(_ca_bundle(database, family, bundle_name))
        sessions[family] = s
    return sessions


def _ca_bundle(database: Path, family: str, name: str) -> Path:
    import certifi

    model_dir = Path(__file__).parent.parent / "models" / family
    intermediate = model_dir / name
    if not intermediate.exists():
        raise SourceUnavailableError(
            f"catalog of {family!r} declares CA bundle {name!r}, which is "
            f"missing from {model_dir}"
        )
    tls_dir = database / ".tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    combined = tls_dir / f"{family}-ca-bundle.pem"
    combined.write_bytes(
        Path(certifi.where()).read_bytes() + b"\n" + intermediate.read_bytes()
    )
    return combined


def _build_product(
    database: Path,
    family: str,
    release: str,
    product: dict,
    session: requests.Session | None,
    verify_existing: bool,
    extract: bool = True,
) -> None:
    target_dir = _product_target(database, family, release, product["label"])
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / product["filename"]
    manifest_path = target_dir / "MANIFEST.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )

    fresh = False
    if archive.exists():
        recorded = manifest.get("sha256")
        if recorded and (not verify_existing or sha256_file(archive) == recorded):
            print(f"keep verified {family}/{release}/{product['label']}")
            sha = recorded
            size = manifest.get("size_bytes")
        else:
            sha, size = _download(product["url"], archive, session)
            fresh = True
    else:
        sha, size = _download(product["url"], archive, session)
        fresh = True

    expected = product.get("size_bytes")
    if expected is not None and fresh and size != expected:
        warnings.warn(
            f"{family}/{release}/{product['label']}: downloaded {size:,} bytes "
            f"but the release catalog recorded {expected:,} bytes; the "
            "upstream file may have been replaced",
            CatalogSizeMismatchWarning,
            stacklevel=2,
        )

    n_data_files = _count_data_files(target_dir)
    if extract and (fresh or n_data_files == 0):
        _safe_extract(archive, target_dir)
        n_data_files = _count_data_files(target_dir)

    manifest.update(
        {
            "family": family,
            "release": release,
            "label": product["label"],
            "kind": product["kind"],
            "physics": product.get("physics"),
            "url": product["url"],
            "sha256": sha,
            "size_bytes": size,
            "expected_size_bytes": product.get("size_bytes"),
            "n_data_files": n_data_files,
            "extracted": n_data_files > 0,
            "retrieved_at": manifest.get("retrieved_at") if not fresh else _now_iso(),
            "source_class": "official_origin",
            "note": catalog(family).get(
                "source_note", "official published package"
            ),
            "format": product.get("format"),
            "references": [r.citation for r in references(family)],
        }
    )
    _atomic_write_json(manifest_path, manifest)
