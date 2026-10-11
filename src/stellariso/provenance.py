"""Provenance schema: sources, assets, chains, and the provenance bundle.

The data-download URL is not the same thing as the paper that should be
cited, and neither is the same as the software that produced a file. These
are recorded separately (``data_sources`` vs ``scientific_references`` vs
``software_references``), and transformations applied between retrieval and
use are recorded as an explicit chain.
"""

from __future__ import annotations

import dataclasses
from enum import Enum

__all__ = [
    "SourceClass",
    "SourceStatus",
    "SourceRecord",
    "DataAsset",
    "SourceChain",
    "Reference",
    "Provenance",
]


class SourceClass(Enum):
    """The kind of channel an asset was obtained through.

    Ordered by trust priority: model-team origins first, archives and
    official software next, third parties last.
    """

    OFFICIAL_ORIGIN = "official_origin"  # the model team's own site
    OFFICIAL_ARCHIVE = "official_archive"  # archive designated by the team
    SCIENTIFIC_ARCHIVE = "scientific_archive"  # CDS, Zenodo, CADC, ...
    OFFICIAL_SOFTWARE_DISTRIBUTION = "official_software_distribution"
    THIRD_PARTY_PACKAGE = "third_party_package"
    HISTORICAL_MIRROR = "historical_mirror"
    LOCAL_USER_FILE = "local_user_file"


class SourceStatus(Enum):
    VERIFIED = "verified"  # retrieved and checksum-validated
    RETRIEVED = "retrieved"  # retrieved, not checksum-validated
    UNAVAILABLE = "unavailable"  # checked and unreachable
    NOT_CHECKED = "not_checked"
    DECLARED = "declared"  # asserted (e.g. by the user), not contacted


@dataclasses.dataclass(frozen=True)
class SourceRecord:
    """One channel through which an asset is (or can be) obtained."""

    source_class: SourceClass
    url: str | None = None
    accessed_at: str | None = None  # ISO-8601 timestamp
    status: SourceStatus = SourceStatus.NOT_CHECKED
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_class, SourceClass):
            raise TypeError("source_class must be a SourceClass")
        if not isinstance(self.status, SourceStatus):
            raise TypeError("status must be a SourceStatus")

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["source_class"] = self.source_class.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SourceRecord":
        d = dict(d)
        d["source_class"] = SourceClass(d["source_class"])
        d["status"] = SourceStatus(d.get("status", "not_checked"))
        return cls(**d)


@dataclasses.dataclass(frozen=True)
class DataAsset:
    """A concrete file held locally, with integrity metadata."""

    filename: str
    size_bytes: int | None = None
    checksum_algorithm: str = "sha256"
    checksum: str | None = None
    retrieved_at: str | None = None
    source: SourceRecord | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        if self.source is not None:
            d["source"] = self.source.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DataAsset":
        d = dict(d)
        if d.get("source") is not None:
            d["source"] = SourceRecord.from_dict(d["source"])
        return cls(**d)


@dataclasses.dataclass(frozen=True)
class SourceChain:
    """The full chain from original publication to the object in hand."""

    upstream_sources: tuple[SourceRecord, ...] = ()
    immediate_source: SourceRecord | None = None
    transformations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "upstream_sources", tuple(self.upstream_sources))
        object.__setattr__(self, "transformations", tuple(self.transformations))

    def to_dict(self) -> dict:
        return {
            "upstream_sources": [s.to_dict() for s in self.upstream_sources],
            "immediate_source": (
                self.immediate_source.to_dict() if self.immediate_source else None
            ),
            "transformations": list(self.transformations),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceChain":
        d = dict(d)
        d["upstream_sources"] = [
            SourceRecord.from_dict(s) for s in d.get("upstream_sources", [])
        ]
        if d.get("immediate_source") is not None:
            d["immediate_source"] = SourceRecord.from_dict(d["immediate_source"])
        d["transformations"] = tuple(d.get("transformations", []))
        return cls(**d)


@dataclasses.dataclass(frozen=True)
class Reference:
    """A scientific or software citation, kept apart from download URLs."""

    citation: str  # human-readable "Author et al. (year), Journal, Vol, Page"
    ads_url: str | None = None
    bibcode: str | None = None
    url: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Reference":
        return cls(**d)


@dataclasses.dataclass(frozen=True)
class Provenance:
    """Everything known about where an object's data came from."""

    data_sources: tuple[SourceRecord, ...] = ()
    assets: tuple[DataAsset, ...] = ()
    source_chains: tuple[SourceChain, ...] = ()
    scientific_references: tuple[Reference, ...] = ()
    software_references: tuple[Reference, ...] = ()
    transformations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "data_sources",
            "assets",
            "source_chains",
            "scientific_references",
            "software_references",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "transformations", tuple(self.transformations))

    def to_dict(self) -> dict:
        return {
            "data_sources": [s.to_dict() for s in self.data_sources],
            "assets": [a.to_dict() for a in self.assets],
            "source_chains": [c.to_dict() for c in self.source_chains],
            "scientific_references": [r.to_dict() for r in self.scientific_references],
            "software_references": [r.to_dict() for r in self.software_references],
            "transformations": list(self.transformations),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Provenance":
        return cls(
            data_sources=tuple(
                SourceRecord.from_dict(s) for s in d.get("data_sources", [])
            ),
            assets=tuple(DataAsset.from_dict(a) for a in d.get("assets", [])),
            source_chains=tuple(
                SourceChain.from_dict(c) for c in d.get("source_chains", [])
            ),
            scientific_references=tuple(
                Reference.from_dict(r) for r in d.get("scientific_references", [])
            ),
            software_references=tuple(
                Reference.from_dict(r) for r in d.get("software_references", [])
            ),
            transformations=tuple(d.get("transformations", [])),
        )
