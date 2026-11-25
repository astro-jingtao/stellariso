"""The read side of the local database: open, list, lazily extract.

``Database`` is the offline query facade over one database root: it
enumerates the product directories, exposes each product's identity
through its (bridged, v2-shaped) MANIFEST, and opens products as
isochrone grids. Package products that were archived without extraction
are extracted on first open, verifying the archive's recorded sha256
first. Manually held files enter through ``register_local_product``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import inspect
import os
from pathlib import Path
import tarfile
import warnings
import zipfile

from stellariso.database.design import adapter_for
from stellariso.database.manifest import (
    primary_part,
    read_manifest,
    utc_now_iso,
    write_manifest,
)
from stellariso.exceptions import SourceUnavailableError
from stellariso.grid import IsochroneGrid
from stellariso.integrity import sha256_file, verify_checksum
from stellariso.models import parse_model_spec
from stellariso.provenance import Provenance, SourceClass, SourceRecord, SourceStatus
from stellariso.registry import references
from stellariso.warnings import ChecksumUnavailableWarning

__all__ = ["Database", "ProductRecord", "open_database", "register_local_product"]

_DATA_SUFFIXES = (".iso", ".track", ".eep", ".dat")

# tarfile's ``filter`` parameter is a security backport (3.9.17+, 3.10.12+,
# 3.11.4+); several supported-interpreter bundles predate it (the windows
# and macos runner images ship such 3.9 and 3.10). The per-member escape
# check in ``_safe_extract`` already refuses any member that resolves
# outside the target, so on interpreters without the parameter the
# extraction runs with the plain legacy behavior the filter tightens.
_EXTRACT_FILTER = (
    {"filter": "data"}
    if "filter" in inspect.signature(tarfile.TarFile.extract).parameters
    else {}
)


def _count_data_files(target_dir: Path) -> int:
    return sum(
        1
        for p in target_dir.rglob("*")
        if p.is_file()
        and (p.suffix.lower() in _DATA_SUFFIXES or p.name.lower().endswith(".iso.gz"))
    )


def _safe_extract(archive_path: Path, target: Path) -> list[str]:
    """Extract a tar or zip archive refusing anything that escapes target."""
    target = target.resolve()
    extracted = []

    def _check(name: str) -> None:
        # containment by common path, not by name-prefix comparison: a
        # member may resolve to a sibling whose name extends the
        # target's (target .../out, member ../out2/...), which a plain
        # startswith test would pass
        dest = (target / name).resolve()
        if os.path.commonpath([str(dest), str(target)]) != str(target):
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
            tf.extract(member, target, **_EXTRACT_FILTER)
            extracted.append(member.name)
    return extracted


@dataclass(frozen=True)
class ProductRecord:
    """One product directory inside a database, described by its MANIFEST.

    ``manifest`` is the v2-shaped view (legacy manifests are bridged on
    read); part facts live under ``manifest["parts"]``.
    """

    directory: Path
    manifest: dict

    @property
    def family(self) -> str:
        """The product's family name (from its MANIFEST)."""
        return self.manifest["family"]

    @property
    def release(self) -> str:
        """The product's release string (from its MANIFEST)."""
        return self.manifest["release"]

    @property
    def label(self) -> str:
        """The product's label within the release (from its MANIFEST)."""
        return self.manifest["label"]

    @property
    def kind(self) -> str | None:
        """The product's kind, when the family distinguishes several."""
        return self.manifest.get("kind")

    def _primary_entry(self) -> dict:
        part = primary_part(self.manifest)
        return (self.manifest.get("parts") or {}).get(part, {}) if part else {}

    @property
    def url(self) -> str | None:
        """The primary part's recorded URL, if any."""
        return self._primary_entry().get("url")

    @property
    def sha256(self) -> str | None:
        """The primary part's recorded sha256, if any."""
        return self._primary_entry().get("sha256")

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"ProductRecord({self.family}/{self.release}/{self.label})"


class Database:
    """An opened local database: the products present under one root."""

    def __init__(self, root: Path) -> None:
        """Open the database rooted at ``root`` and index its products."""
        self.root = root
        self._products = tuple(
            ProductRecord(directory=manifest.parent, manifest=read_manifest(manifest))
            for manifest in sorted(root.glob("*/*/*/MANIFEST.json"))
        )

    @property
    def products(self) -> tuple[ProductRecord, ...]:
        """Every product directory found under the root."""
        return self._products

    def products_for(self, family: str, release: str | None = None) -> tuple[ProductRecord, ...]:
        """The products of one family, optionally narrowed to one release."""
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
        publishes several products (rotation sets, column variants),
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
        against the recorded sha256 and extracts it then — the archive
        itself always stays (it is the true original data). Already-
        extracted and manually-registered products are returned as-is
        (what counts as a data file is the family adapter's call:
        extension-less native names are data too).
        """
        adapter = adapter_for(record.family)
        if any(
            adapter.is_data_file(p)
            for p in record.directory.rglob("*")
            if p.is_file()
        ):
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
        expected = record.sha256
        if expected:
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
        write_manifest(record.directory / "MANIFEST.json", manifest)

    def describe(self) -> str:
        """A short human summary of the database (paths, sizes, releases)."""
        lines = [f"stellariso database at {self.root}", f"products: {len(self._products)}"]
        for p in self._products:
            size = p._primary_entry().get("size_bytes")
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
                    url=record.url,
                    accessed_at=record._primary_entry().get("retrieved_at"),
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


# -- manual registration (sources without package channels) --------------------


def register_local_product(
    database: str | Path,
    family: str,
    release: str,
    label: str,
    *,
    files: Iterable[Path],
    note: str,
) -> ProductRecord:
    """Register locally held files as a product of the database.

    For files obtained outside the package catalogs (e.g. a CMD web-form
    table downloaded by hand in a browser), the files are placed in one
    directory and described here — with a v2 MANIFEST, an explicit
    ``local_user_file`` source class, one part per file (checksummed at
    registration), and the acquisition note stating exactly how the
    files were produced.
    """
    root = Path(database)
    target_dir = root / family / release / label
    target_dir.mkdir(parents=True, exist_ok=True)
    parts: dict[str, dict] = {}
    for f in files:
        src = Path(f)
        dest = target_dir / src.name
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        parts[src.name] = {
            "file": src.name,
            "sha256": sha256_file(dest),
            "size_bytes": dest.stat().st_size,
            "retrieved_at": utc_now_iso(),
        }
    manifest = {
        "family": family,
        "release": release,
        "label": label,
        "kind": "local_user_files",
        "physics": None,
        "source_class": SourceClass.LOCAL_USER_FILE.value,
        "note": note,
        "parts": parts,
        "references": [r.citation for r in references(family)],
    }
    write_manifest(target_dir / "MANIFEST.json", manifest)
    # inventory imports Database from this module — cycle breaker, one side
    # must stay function-local
    from stellariso.database.inventory import write_inventory  # noqa: PLC0415

    write_inventory(root)
    return ProductRecord(directory=target_dir, manifest=read_manifest(target_dir / "MANIFEST.json"))
