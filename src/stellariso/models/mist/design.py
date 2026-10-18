"""The MIST family adapter: the release catalog seen through the generic
database machinery.

Every product is one official package: a single ``archive`` part
downloaded from the published tarball surface (``mist.science/data/``,
verified in the catalog data), extracted on demand by the core. The
catalog (``models/mist/catalog.json``) is the design; directory
identity is (release, label) against the catalog. Upstream publishes
no checksums — sha256 is computed at download time and recorded, and
the catalog's recorded size serves as a replaced-file tripwire (a
deviation warns, it does not fail: the archive's own recorded sha is
the integrity anchor).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Iterator

from stellariso.database.design import (
    DirectoryMatch,
    FamilyAdapter,
    PartDesign,
    PartVerdict,
    ProductDesign,
)
from stellariso.integrity import sha256_file
from stellariso.models import catalog as load_catalog
from stellariso.registry import references
from stellariso.warnings import CatalogSizeMismatchWarning

__all__ = ["MistAdapter"]

_CHUNK = 1 << 20
_TIMEOUT_GET = 1800


def download_file(url: str, target: Path, session) -> tuple[str, int]:
    """Stream one package to its target; return (sha256, size_bytes)."""
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


class MistAdapter(FamilyAdapter):
    family = "mist"

    def _catalog(self) -> dict:
        return load_catalog("mist")

    # -- enumeration ------------------------------------------------------

    def designs(self) -> Iterator[ProductDesign]:
        for release_entry in self._catalog()["releases"]:
            for product in release_entry["products"]:
                yield ProductDesign(
                    family="mist",
                    collection=release_entry["release"],
                    label=product["label"],
                    kind=product["kind"],
                    parts=(PartDesign(name="archive", filename=product["filename"]),),
                    facts={
                        "url": product["url"],
                        "filename": product["filename"],
                        "size_bytes": product.get("size_bytes"),
                        "format": product.get("format"),
                        "physics": product.get("physics"),
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
        self, design: ProductDesign, part: PartDesign, directory: Path, manifest: dict
    ) -> PartVerdict:
        path = directory / part.filename
        if not path.exists():
            return PartVerdict.missing()
        entry = (manifest.get("parts") or {}).get(part.name) or {}
        recorded = entry.get("sha256")
        if recorded is None:
            return PartVerdict.ok(
                f"{part.filename}: no sha256 recorded in its MANIFEST; "
                "integrity not verified"
            )
        actual = sha256_file(path)
        if actual != recorded:
            return PartVerdict.nonconforming(
                f"{part.filename}: sha256 mismatch — recorded {recorded}, "
                f"file hashes {actual}"
            )
        expected = design.facts.get("size_bytes")
        if expected is not None and path.stat().st_size != expected:
            return PartVerdict.ok(
                f"{part.filename}: {path.stat().st_size:,} bytes on disk but the "
                f"release catalog recorded {expected:,} bytes; the upstream "
                "file may have been replaced"
            )
        return PartVerdict.ok()

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
            import requests

            session = requests.Session()
            session.headers["User-Agent"] = "stellariso (isochrone database builder)"
        from stellariso.database.manifest import utc_now_iso

        url = design.facts["url"]
        sha, size = download_file(url, directory / part.filename, session)
        expected = design.facts.get("size_bytes")
        if expected is not None and size != expected:
            import warnings

            warnings.warn(
                f"{design.relative_dir}: downloaded {size:,} bytes but the "
                f"release catalog recorded {expected:,} bytes; the upstream "
                "file may have been replaced",
                CatalogSizeMismatchWarning,
                stacklevel=2,
            )
        return {
            "file": part.filename,
            "sha256": sha,
            "size_bytes": size,
            "expected_size_bytes": expected,
            "retrieved_at": utc_now_iso(),
            "url": url,
        }

    # -- report ---------------------------------------------------------------

    def fetch_cost(self, design: ProductDesign, part: PartDesign) -> dict:
        return {"kind": "download", "size_bytes": design.facts.get("size_bytes")}

    def report_header(self, designs) -> list[str]:
        cat = self._catalog()
        releases = cat["releases"]
        sizes = [p.get("size_bytes") or 0 for r in releases for p in r["products"]]
        lines = [
            "Source: official published packages "
            "(https://mist.science/data/ tarballs; upstream publishes no "
            "checksums — sha256 computed at download and recorded).",
        ]
        for release_entry in releases:
            products = release_entry["products"]
            lines.append(
                f"- release {release_entry['release']}: {len(products)} "
                f"packages ({', '.join(sorted(p['label'] for p in products))})"
            )
        lines.append(
            f"Total published size of the designed packages: {sum(sizes):,} bytes"
        )
        return lines
