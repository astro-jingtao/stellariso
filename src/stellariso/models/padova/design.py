"""The Padova family adapter: the VizieR archives seen through the
generic database machinery.

Every product is one static CDS/VizieR catalog directory, acquired as
its in-scope files (the release catalog lists each file's exact URL,
size, and the sha256 verified at download time — upstream publishes no
checksums). Two channels matter: the canonical cdsarc host is
unreachable from this network (proxy tunnel failure), so acquisition
goes through the ADAC mirror's native tree over plain HTTP; the channel
actually used is recorded in every MANIFEST.

Each ``.gz`` part is kept verbatim as the integrity anchor and
decompressed beside it at fetch time (``extracts`` stays False: there is
no archive container, and the total directory is a few MB — an
archives-only mode would save nothing). The decompressed twins carry the
canonical file names the 1994 reader requires.
"""

from __future__ import annotations

import gzip
import re
import shutil
import warnings
from pathlib import Path
from typing import Callable, Iterator

from stellariso.database.design import (
    DirectoryMatch,
    FamilyAdapter,
    PartDesign,
    PartVerdict,
    ProductDesign,
)
from stellariso.integrity import download_file, sha256_file
from stellariso.models import catalog as load_catalog
from stellariso.registry import references
from stellariso.warnings import CatalogChecksumMismatchWarning, CatalogSizeMismatchWarning

__all__ = ["PadovaAdapter"]

_TIMEOUT_GET = 1800

_VIZIER_CATALOG: dict[str, str] = {
    "1994": "J/A+AS/106/275",
    "2000": "J/A+AS/141/371",
}

_TABLE_NAME = re.compile(r"table[1-6]$")


def _default_session():
    import requests

    session = requests.Session()
    session.headers["User-Agent"] = "stellariso (isochrone database builder)"
    return session


class PadovaAdapter(FamilyAdapter):
    family = "padova"

    # -- enumeration ------------------------------------------------------

    def _catalog(self) -> dict:
        return load_catalog("padova")

    def designs(self) -> Iterator[ProductDesign]:
        for release_entry in self._catalog()["releases"]:
            for product in release_entry["products"]:
                files = {f["part"]: f for f in product["files"]}
                yield ProductDesign(
                    family="padova",
                    collection=release_entry["release"],
                    release=release_entry["release"],
                    label=product["label"],
                    kind=product["kind"],
                    parts=tuple(
                        PartDesign(name=f["part"], filename=f["filename"])
                        for f in product["files"]
                    ),
                    facts={
                        "files": files,
                        "format": product.get("format"),
                        "physics": product.get("physics"),
                        "total_bytes": sum(
                            f.get("size_bytes") or 0 for f in product["files"]
                        ),
                    },
                )

    # -- directory mapping --------------------------------------------------

    def product_of_directory(self, root: Path, directory: Path) -> DirectoryMatch:
        release = directory.parent.name
        label = directory.name
        for design in self.designs():
            if design.collection == release and design.label == label:
                return DirectoryMatch(design)
        if any(d.collection == release for d in self.designs()):
            return DirectoryMatch(
                None, f"label {label!r} is not a catalog product of release {release!r}"
            )
        return DirectoryMatch(None, f"release {release!r} is not in the catalog")

    # -- classification -----------------------------------------------------

    def classify_part(
        self,
        design: ProductDesign,
        part: PartDesign,
        directory: Path,
        manifest: dict,
        *,
        verify: bool = True,
    ) -> PartVerdict:
        path = directory / part.filename
        if not path.exists():
            return PartVerdict.missing()
        facts = design.facts["files"][part.name]
        entry = (manifest.get("parts") or {}).get(part.name) or {}
        recorded = entry.get("sha256")
        if verify:
            if recorded is None:
                return self._conformity(path, facts, no_manifest_sha=True)
            actual = sha256_file(path)
            if actual != recorded:
                return PartVerdict.nonconforming(
                    f"{part.filename}: sha256 mismatch — recorded {recorded}, "
                    f"file hashes {actual}"
                )
            return self._conformity(path, facts, actual=actual)
        return self._conformity(path, facts, no_manifest_sha=recorded is None)

    def _conformity(
        self,
        path: Path,
        facts: dict,
        *,
        no_manifest_sha: bool = False,
        actual: str | None = None,
    ) -> PartVerdict:
        """Intact-part caveats: the catalog's verified values are
        tripwires for an upstream-replaced file (a warning, never a
        failure — the MANIFEST's own recorded sha is the anchor)."""
        notes = []
        if no_manifest_sha:
            notes.append(
                f"{path.name}: no sha256 recorded in its MANIFEST; "
                "integrity not verified"
            )
        expected_sha = facts.get("sha256")
        if expected_sha is not None and actual is not None and actual != expected_sha:
            notes.append(
                f"{path.name}: hashes to {actual} but the release "
                f"catalog recorded {expected_sha} (verified at "
                "acquisition design time); the upstream file may "
                "have been replaced"
            )
        expected_size = facts.get("size_bytes")
        if expected_size is not None and path.stat().st_size != expected_size:
            notes.append(
                f"{path.name}: {path.stat().st_size:,} bytes on disk but "
                f"the release catalog recorded {expected_size:,} bytes"
            )
        return PartVerdict.ok(*notes)

    # -- fetching -----------------------------------------------------------

    def fetch_part(
        self,
        design: ProductDesign,
        part: PartDesign,
        directory: Path,
        *,
        session=None,
        client=None,
        log: Callable[[str], None] = print,
    ) -> dict:
        if session is None:
            session = _default_session()
        from stellariso.database.manifest import utc_now_iso

        facts = design.facts["files"][part.name]
        url = facts["url"]
        sha, size = download_file(url, directory / part.filename, session)
        expected_sha = facts.get("sha256")
        if expected_sha is not None and sha != expected_sha:
            warnings.warn(
                f"{design.relative_dir}: {part.filename} hashes to {sha} "
                f"but the release catalog recorded {expected_sha} "
                "(verified at acquisition design time); the upstream file "
                "may have been replaced",
                CatalogChecksumMismatchWarning,
                stacklevel=2,
            )
        expected_size = facts.get("size_bytes")
        if expected_size is not None and size != expected_size:
            warnings.warn(
                f"{design.relative_dir}: downloaded {size:,} bytes but the "
                f"release catalog recorded {expected_size:,} bytes; the "
                "upstream file may have been replaced",
                CatalogSizeMismatchWarning,
                stacklevel=2,
            )
        entry = {
            "file": part.filename,
            "sha256": sha,
            "size_bytes": size,
            "retrieved_at": utc_now_iso(),
            "url": url,
        }
        if expected_sha is not None:
            entry["catalog_sha256"] = expected_sha
        if part.filename.endswith(".gz"):
            plain = directory / part.filename[:-3]
            with gzip.open(directory / part.filename, "rb") as src, open(
                plain, "wb"
            ) as dst:
                shutil.copyfileobj(src, dst)
            entry["decompressed"] = plain.name
            entry["decompressed_sha256"] = sha256_file(plain)
        return entry

    # -- manifest and report ---------------------------------------------------

    def manifest_fields(self, design: ProductDesign) -> dict:
        vizier = _VIZIER_CATALOG[design.release]
        return {
            "source_class": "scientific_archive",
            "note": (
                f"CDS/VizieR static catalog archive {vizier}, acquired "
                "file-by-file from the ADAC mirror's native tree "
                "(http://vizier.nao.ac.jp/ftp/cats) over plain HTTP (the "
                "canonical cdsarc host is unreachable from this network); "
                "upstream publishes no checksums — sha256 computed at "
                "download; each .gz part is kept verbatim beside its "
                "decompressed twin"
            ),
            "format": design.facts.get("format"),
            "physics": design.facts.get("physics"),
            "references": [r.citation for r in references("padova")],
        }

    def family_section(self, design: ProductDesign) -> dict:
        return {
            "vizier_catalog": _VIZIER_CATALOG[design.release],
            "channel": "adac_mirror_native_tree",
            "canonical_host": "cdsarc.cds.unistra.fr",
        }

    def fetch_cost(self, design: ProductDesign, part: PartDesign) -> dict:
        return {
            "kind": "download",
            "size_bytes": design.facts["files"][part.name].get("size_bytes"),
        }

    def is_data_file(self, path: Path) -> bool:
        name = path.name
        if name.endswith(".gz"):
            name = name[:-3]
        return bool(_TABLE_NAME.match(name)) or name in (
            "isochron.dat",
            "isochsum.dat",
        )

    def report_header(self, designs) -> list[str]:
        cat = self._catalog()
        mirror = cat["mirror_base"]
        lines = [
            "Source: static CDS/VizieR catalog archives "
            "(J/A+AS/106/275 Bertelli et al. 1994; J/A+AS/141/371 "
            "Girardi et al. 2000); the original host pleiadi.pd.astro.it "
            "is effectively dead.",
            f"Channel: ADAC mirror native tree ({mirror}) — plain HTTP, "
            "no upstream checksums; sha256 computed at download (the "
            "release catalog's values were verified identical on "
            "2026-11-10 and 2026-11-12). The canonical cdsarc host is "
            "unreachable from this network.",
        ]
        total = 0
        for release_entry in cat["releases"]:
            for product in release_entry["products"]:
                n = len(product["files"])
                size = sum(f.get("size_bytes") or 0 for f in product["files"])
                total += size
                lines.append(
                    f"- release {release_entry['release']} "
                    f"{product['label']}: {n} files, {size:,} bytes "
                    "(ReadMe + the isochrone tables; tracks, surface "
                    "compositions, SSP colors, and postscript renderings "
                    "out of scope)"
                )
        lines.append(f"Total published size of the designed files: {total:,} bytes")
        return lines
