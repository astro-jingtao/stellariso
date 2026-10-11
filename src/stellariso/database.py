"""The local isochrone database: explicit, self-contained, portable.

A database is one user-chosen directory built once by ``build_database``
downloading the complete published matrix (every release and every
parameter set the sources offer, as official packages — never on-demand
computed subsets) and queried afterwards by ``open_database`` fully
offline. There is no environment-variable lookup and no implicit
location: every entry point takes ``database`` explicitly.

Layout::

    <database>/
        database.json                # inventory of every product
        README.md                    # human summary, format notes, citations
        unified-parameters.md        # mapping documentation snapshot
        <family>/<release>/<product>/
            MANIFEST.json            # source, checksum, identity, format
            <archive>.txz            # the official package, kept
            <extracted data files>

Self-containment: each MANIFEST records what the data is, where it came
from, its checksum, the file format, and the literature to cite, so the
database stays interpretable with the upstream websites gone. Only
relative paths are stored — the whole database, or any subset of its
product directories, can be copied to another machine and opened there.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import warnings
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

from stellariso.exceptions import SourceUnavailableError
from stellariso.grid import IsochroneGrid
from stellariso.integrity import sha256_file
from stellariso.models import catalog, parse_model_spec
from stellariso.provenance import Provenance, SourceClass, SourceRecord, SourceStatus
from stellariso.registry import backend_names, references
from stellariso.warnings import CatalogSizeMismatchWarning, ChecksumUnavailableWarning

__all__ = ["Database", "ProductRecord", "build_database", "open_database"]

_CHUNK = 1 << 20
_TIMEOUT_GET = 1800


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- manifests ----------------------------------------------------------------


@dataclass(frozen=True)
class ProductRecord:
    """One product directory inside a database, described by its MANIFEST."""

    directory: Path
    manifest: dict

    @property
    def family(self) -> str:
        return self.manifest["family"]

    @property
    def release(self) -> str:
        return self.manifest["release"]

    @property
    def label(self) -> str:
        return self.manifest["label"]

    @property
    def url(self) -> str | None:
        return self.manifest.get("url")

    @property
    def sha256(self) -> str | None:
        return self.manifest.get("sha256")

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"ProductRecord({self.family}/{self.release}/{self.label})"


class Database:
    """An opened local database: the products present under one root."""

    def __init__(self, root: Path):
        self.root = root
        self._products = tuple(
            ProductRecord(directory=manifest.parent, manifest=json.loads(manifest.read_text(encoding="utf-8")))
            for manifest in sorted(root.glob("*/*/*/MANIFEST.json"))
        )

    @property
    def products(self) -> tuple[ProductRecord, ...]:
        return self._products

    def products_for(self, family: str, release: str | None = None) -> tuple[ProductRecord, ...]:
        return tuple(
            p
            for p in self._products
            if p.family == family and (release is None or p.release == release)
        )

    def grid(
        self,
        model: str,
        label: str | None = None,
    ) -> IsochroneGrid:
        """Open one product as a grid.

        ``model`` is version-qualified (``"mist/1.2"``). When a release
        publishes several products (rotation sets, isochrone/tracks kinds),
        ``label`` picks one; without ``label`` the choice must be unique.
        """
        family, release = parse_model_spec(model)
        if release is None:
            raise ValueError(
                f"model must be version-qualified, e.g. 'mist/1.2'; got {model!r}"
            )
        candidates = self.products_for(family, release)
        if not candidates:
            raise SourceUnavailableError(
                f"database {self.root} holds no {family}/{release} product; "
                f"present: {[repr(p) for p in self._products]}"
            )
        if label is not None:
            candidates = tuple(p for p in candidates if p.label == label)
            if not candidates:
                raise ValueError(
                    f"no product labeled {label!r} for {family}/{release}; "
                    f"available: {[p.label for p in self.products_for(family, release)]}"
                )
        if len(candidates) > 1:
            raise ValueError(
                f"{family}/{release} has {len(candidates)} products; pin one "
                f"of {[p.label for p in candidates]} with label="
            )
        record = candidates[0]
        self._ensure_extracted(record)
        return IsochroneGrid.from_directory(family, record.directory)

    def _ensure_extracted(self, record: ProductRecord) -> None:
        """Extract a not-yet-extracted product on first open.

        Archives-only databases (``build_database(..., extract=False)``)
        keep every official package without paying the several-fold
        extracted size on disk; opening a product verifies the archive
        against the recorded sha256 and extracts it then. Already-extracted
        and manually-registered products are returned as-is.
        """
        if _count_data_files(record.directory) > 0:
            return
        archives = [
            p
            for p in record.directory.iterdir()
            if p.is_file() and p.suffix.lower() in (".txz", ".zip", ".tar")
        ]
        if not archives:
            raise SourceUnavailableError(
                f"product {record.family}/{record.release}/{record.label} has "
                f"neither extracted data files nor an archive in "
                f"{record.directory}"
            )
        if len(archives) > 1:
            raise ValueError(
                f"product {record.family}/{record.release}/{record.label} "
                f"holds several archives: {[a.name for a in archives]}"
            )
        archive = archives[0]
        expected = record.manifest.get("sha256")
        if expected:
            from stellariso.integrity import verify_checksum

            verify_checksum(archive, expected)
        else:
            warnings.warn(
                f"{archive.name}: no sha256 recorded in its MANIFEST; "
                "extracting without verification",
                ChecksumUnavailableWarning,
                stacklevel=2,
            )
        _safe_extract(archive, record.directory)
        manifest = dict(record.manifest)
        manifest["n_data_files"] = _count_data_files(record.directory)
        manifest["extracted"] = True
        _atomic_write_json(record.directory / "MANIFEST.json", manifest)

    def describe(self) -> str:
        lines = [f"stellariso database at {self.root}", f"products: {len(self._products)}"]
        for p in self._products:
            size = p.manifest.get("size_bytes")
            size_text = f", {size:,} bytes" if size else ""
            lines.append(f"  {p.family}/{p.release}/{p.label}{size_text}")
        return "\n".join(lines)

    def provenance(self, model: str, label: str | None = None) -> Provenance:
        """The acquisition provenance of one product."""
        record = self._single_record(model, label)
        m = record.manifest
        return Provenance(
            data_sources=(
                SourceRecord(
                    source_class=SourceClass(m.get("source_class", "official_origin")),
                    url=m.get("url"),
                    accessed_at=m.get("retrieved_at"),
                    status=SourceStatus.RETRIEVED,
                    note=m.get("note"),
                ),
            ),
            scientific_references=references(record.family),
        )

    def _single_record(self, model: str, label: str | None) -> ProductRecord:
        family, release = parse_model_spec(model)
        if release is None:
            raise ValueError(
                f"model must be version-qualified, e.g. 'mist/1.2'; got {model!r}"
            )
        candidates = self.products_for(family, release)
        if label is not None:
            candidates = tuple(p for p in candidates if p.label == label)
        if len(candidates) != 1:
            raise ValueError(
                f"expected exactly one product for {model!r}"
                + (f" label={label!r}" if label else "")
                + f"; found {len(candidates)}"
            )
        return candidates[0]


def open_database(database: str | Path) -> Database:
    """Open a local database built by ``build_database`` (or a partial copy)."""
    root = Path(database)
    if not root.is_dir():
        raise NotADirectoryError(
            f"{root} is not a database directory; build one first with "
            "stellariso.build_database(database=...)"
        )
    return Database(root)


# -- building -----------------------------------------------------------------


def _safe_extract(archive_path: Path, target: Path) -> list[str]:
    """Extract a tar or zip archive refusing anything that escapes target."""
    target = target.resolve()
    extracted = []

    def _check(name: str) -> None:
        dest = (target / name).resolve()
        if not str(dest).startswith(str(target)):
            raise ValueError(
                f"archive member {name!r} escapes the target directory"
            )

    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            for info in zf.infolist():
                _check(info.filename)
                zf.extract(info, target)
                extracted.append(info.filename)
        return extracted

    with tarfile.open(archive_path, mode="r:*") as tf:
        for member in tf.getmembers():
            _check(member.name)
            tf.extract(member, target, filter="data")
            extracted.append(member.name)
    return extracted


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


_DATA_SUFFIXES = (".iso", ".track", ".eep", ".dat")


def _count_data_files(target_dir: Path) -> int:
    return sum(
        1
        for p in target_dir.rglob("*")
        if p.is_file()
        and (p.suffix.lower() in _DATA_SUFFIXES or p.name.lower().endswith(".iso.gz"))
    )


def build_database(
    database: str | Path,
    models: Iterable[str] | None = None,
    session: requests.Session | None = None,
    verify_existing: bool = True,
    dry_run: bool = False,
    extract: bool = True,
) -> Database | None:
    """Build (or complete) a local database with the full published matrix.

    Every release and every parameter set each registered source publishes
    as an official package is downloaded, checksummed, extracted, and
    recorded in a per-product MANIFEST; nothing is fetched on demand and no
    web-form-computed subsets are used. Products already present with a
    matching checksum are kept as-is (re-verified unless
    ``verify_existing=False``).

    ``models`` limits the build to the given families (default: all).
    ``dry_run=True`` only reports what would be downloaded. With
    ``extract=False`` only the official archives are kept (the complete,
    self-contained backup); ``Database.grid`` extracts a product on first
    open, verifying the archive's sha256 first — the right mode when the
    disk cannot hold the extracted form of every package at once (the
    extracted size is several times the archive size).
    """
    root = Path(database)
    families = list(models) if models is not None else list(backend_names())

    catalogs = {family: catalog(family) for family in families}
    for family, cat in catalogs.items():
        if cat.get("channel") == "manual":
            _fail_manual(root, family, cat)

    jobs = []
    for family in families:
        cat = catalogs[family]
        for release_entry in cat["releases"]:
            for product in release_entry["products"]:
                jobs.append((family, release_entry["release"], product))

    if dry_run:
        total = 0
        missing_size = 0
        for family, release, product in jobs:
            size = product.get("size_bytes")
            if size is None:
                missing_size += 1
                size_text = "size unknown"
            else:
                total += size
                size_text = f"{size:,} bytes"
            print(f"{family}/{release}/{product['label']}  {size_text}  {product['url']}")
        print(
            f"{len(jobs)} product(s), {total:,} bytes total "
            f"({total / 1e9:.1f} GB, {missing_size} with unknown size)"
        )
        return None

    root.mkdir(parents=True, exist_ok=True)
    sessions = _sessions(root, families, session)

    for family, release, product in jobs:
        _build_product(
            root, family, release, product, sessions[family], verify_existing,
            extract=extract,
        )

    _write_inventory(root)
    return open_database(root)


def _fail_manual(database: Path, family: str, cat: dict) -> None:
    raise SourceUnavailableError(
        f"{family} publishes no downloadable packages: {cat.get('manual_note', '')} "
        f"(full procedure: docs/data-sources.md). Obtain the files, put them "
        f"under {database / family}, and create their MANIFESTs with "
        f"stellariso.register_local_product()."
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

    model_dir = Path(__file__).parent / "models" / family
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


def _write_inventory(root: Path) -> None:
    from stellariso import __version__

    products = Database(root).products
    inventory = {
        "stellariso_version": __version__,
        "generated_at": _now_iso(),
        "products": [
            {
                "family": p.family,
                "release": p.release,
                "label": p.label,
                "kind": p.manifest.get("kind"),
                "url": p.url,
                "sha256": p.sha256,
                "size_bytes": p.manifest.get("size_bytes"),
            }
            for p in products
        ],
    }
    _atomic_write_json(root / "database.json", inventory)

    lines = [
        "# stellariso isochrone database",
        "",
        f"Built by stellariso {__version__} on {inventory['generated_at']}.",
        "",
        "Each `<family>/<release>/<label>` directory is one official published "
        "package: the archive as downloaded, the extracted data files, and a "
        "MANIFEST.json recording the source URL, sha256, size, retrieval "
        "time, file format, and the literature to cite. The database is "
        "self-contained: with the upstream websites gone, the manifests and "
        "the copied mapping documentation below still explain every file.",
        "",
        "The whole database, or any subset of its product directories, can "
        "be copied to another machine and opened there:",
        "",
        "```python",
        "import stellariso",
        f"db = stellariso.open_database({str(root)!r})",
        "grid = db.grid('mist/1.2', label='vvcrit0.4_full_isos')",
        "```",
        "",
        "## Products",
        "",
        "| Product | Kind | Size (bytes) | Source |",
        "|---|---|---|---|",
    ]
    for p in products:
        size = p.manifest.get("size_bytes")
        lines.append(
            f"| `{p.family}/{p.release}/{p.label}` | {p.manifest.get('kind')} "
            f"| {size if size else '—'} | {p.url or 'manual'} |"
        )
    lines += [
        "",
        "## Citations",
        "",
    ]
    seen = set()
    for p in products:
        for citation in p.manifest.get("references", []):
            if citation not in seen:
                seen.add(citation)
                lines.append(f"- {citation}")
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    from stellariso.registry.docs import render_documentation

    (root / "unified-parameters.md").write_text(
        render_documentation(), encoding="utf-8", newline="\n"
    )


# -- manual registration (sources without package channels) --------------------


def register_local_product(
    database: str | Path,
    family: str,
    release: str,
    label: str,
    files: Iterable[Path],
    note: str,
) -> ProductRecord:
    """Register manually obtained files as a product of the database.

    For sources that publish no downloadable packages (PARSEC today), the
    files are obtained by hand through the official interface, placed in
    one directory, and described here — with the same MANIFEST shape the
    builder writes, an explicit ``local_user_file`` source class, and the
    acquisition note stating exactly how the files were produced.
    """
    from stellariso.provenance import SourceClass as _SC

    root = Path(database)
    target_dir = _product_target(root, family, release, label)
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in files:
        src = Path(f)
        dest = target_dir / src.name
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        copied.append(dest.name)

    manifest = {
        "family": family,
        "release": release,
        "label": label,
        "kind": "local_user_files",
        "physics": None,
        "url": None,
        "sha256": None,
        "size_bytes": sum((target_dir / n).stat().st_size for n in copied),
        "retrieved_at": _now_iso(),
        "source_class": _SC.LOCAL_USER_FILE.value,
        "note": note,
        "files": copied,
        "references": [r.citation for r in references(family)],
    }
    _atomic_write_json(target_dir / "MANIFEST.json", manifest)
    _write_inventory(root)
    return ProductRecord(directory=target_dir, manifest=manifest)
