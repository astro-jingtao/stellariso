"""Designs, parts, verdicts, and the family adapter contract.

The database management machinery (scan, build, transfer, inventory) is
family-agnostic: it works in terms of *designs* — what a source declares
the finished database holds — and *parts* — the acquisition units a
product is made of. Each isochrone source implements one
:class:`FamilyAdapter` and thereby gains every capability; nothing else
in the library specializes on a family.

Two-state model. A product is ``complete`` exactly when every designed
part is ``ok``; any missing or nonconforming part makes it
``incomplete``. Which part is missing, and why a part is off-design,
live in per-part verdicts with reasons — never in product-level status
names. A product holding any nonconforming part is never auto-completed
by the builder or the merger (a checksum proves integrity, not design
membership), and re-fetching such data stays a human decision reported
separately from automatically planned missing-part jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from stellariso.exceptions import UnsupportedModelError

__all__ = [
    "PartDesign",
    "ProductDesign",
    "PartVerdict",
    "DirectoryMatch",
    "SelectionCriteria",
    "FamilyAdapter",
    "register_adapter",
    "adapter_for",
    "adapter_families",
]


@dataclass(frozen=True)
class PartDesign:
    """One acquisition unit of a product, and its on-disk filename."""

    name: str  # "archive" | "log" | "linear" | ...
    filename: str  # the file inside the product directory


@dataclass(frozen=True)
class ProductDesign:
    """One product the finished database will hold.

    ``collection`` is the directory second level — the release for
    package families (MIST ``1.2``), the set key for form families
    (PARSEC ``v1.2S_COLIBRI_web``). ``facts`` carries whatever the
    family's adapter needs to classify and fetch (MIST: catalog url and
    size; PARSEC: the blueprint cell); the core never interprets it.
    """

    family: str
    collection: str
    label: str
    kind: str
    parts: tuple[PartDesign, ...]
    facts: Mapping[str, Any]

    @property
    def key(self) -> str:
        return f"{self.collection}/{self.label}"

    @property
    def relative_dir(self) -> str:
        return f"{self.family}/{self.collection}/{self.label}"

    def part_named(self, name: str) -> PartDesign:
        for part in self.parts:
            if part.name == name:
                return part
        raise KeyError(f"design {self.relative_dir} has no part {name!r}")


@dataclass(frozen=True)
class PartVerdict:
    """The two-state classification of one part.

    ``kind`` is ``ok``, ``missing``, or ``nonconforming``; ``reasons``
    block (they make the part nonconforming or explain a miss),
    ``warnings`` do not (an intact part with a caveat the design
    tolerates — the upstream-replaced-file posture).
    """

    kind: str
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def ok(cls, *warnings: str) -> "PartVerdict":
        return cls("ok", warnings=warnings)

    @classmethod
    def missing(cls, *reasons: str) -> "PartVerdict":
        return cls("missing", reasons=reasons)

    @classmethod
    def nonconforming(cls, *reasons: str) -> "PartVerdict":
        return cls("nonconforming", reasons=reasons)


@dataclass(frozen=True)
class DirectoryMatch:
    """What a product directory on disk maps to in the design.

    ``design`` set — the directory is this designed product's home.
    ``design`` None — the directory maps nowhere in the design
    (superseded); ``superseded_reason`` says why, family-specific.
    """

    design: ProductDesign | None = None
    superseded_reason: str | None = None

    @property
    def matched(self) -> bool:
        return self.design is not None


@dataclass(frozen=True)
class SelectionCriteria:
    """Declarative product selection for export and merge.

    The generic fields match on design identity; ``states`` filters on
    the scan state (applied by the transfer layer, which holds the scan)
    with ``("complete",)`` the default — finished products — and
    ``("complete", "incomplete")`` the seeding posture for a second
    build machine. ``axes`` carries family-specific filters (for PARSEC:
    ``mh``, ``omega``, ``eta``, ``n_inTPC``, ``dust_m``, ``dust_c``,
    ``lpv``, ``tier``) which the family adapter interprets against its
    own facts. No filter set means no restriction — the whole database.
    """

    families: tuple[str, ...] | None = None
    collections: tuple[str, ...] | None = None
    labels: tuple[str, ...] | None = None
    products: tuple[str, ...] | None = None  # explicit family/collection/label
    states: tuple[str, ...] = ("complete",)
    target_only: bool = False
    axes: Mapping[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        if self.products:
            return f"products {list(self.products)}"
        parts = []
        if self.families:
            parts.append(f"families {list(self.families)}")
        if self.collections:
            parts.append(f"collections {list(self.collections)}")
        if self.labels:
            parts.append(f"labels {list(self.labels)}")
        if self.states != ("complete",):
            parts.append(f"states {list(self.states)}")
        if self.target_only:
            parts.append("target only")
        if self.axes:
            parts.append(f"axes {dict(self.axes)}")
        return "; ".join(parts) or "everything"


class FamilyAdapter:
    """The contract one isochrone source fulfills to gain the whole
    database management stack.

    Subclasses implement the abstract verbs (raising
    ``NotImplementedError`` here): enumerate the design, map a directory
    into it, judge one part, fetch one part, and declare themselves for
    the report. The defaults carry the family-agnostic behavior —
    ``committed`` equals ``designs`` unless the source fetches in stages.
    """

    family: str = ""

    def designs(self) -> Iterable[ProductDesign]:
        """Every product the source declares for a finished database."""
        raise NotImplementedError

    def committed(self) -> Iterable[ProductDesign]:
        """The products the current fetch stage commits to acquiring."""
        return self.designs()

    def product_of_directory(self, root: Path, directory: Path) -> DirectoryMatch:
        """Map one on-disk product directory into the design."""
        raise NotImplementedError

    def classify_part(
        self, design: ProductDesign, part: PartDesign, directory: Path, manifest: dict
    ) -> PartVerdict:
        """Judge one designed part of one on-disk product directory."""
        raise NotImplementedError

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
        """Acquire one part into its directory; return its parts entry
        (file / sha256 / size_bytes / retrieved_at / record / url)."""
        raise NotImplementedError

    def report_header(self, designs: list[ProductDesign]) -> list[str]:
        """The source's declaration lines for the status report."""
        return []

    def family_section(self, design: ProductDesign) -> dict | None:
        """The v2 manifest's family-specific section, if the family has one."""
        return None

    def fetch_cost(self, design: ProductDesign, part: PartDesign) -> dict:
        """What fetching one missing part costs: a download with a known
        size, or a form submission."""
        return {"kind": "submit"}

    def matches_criteria(self, design: ProductDesign, criteria: SelectionCriteria) -> bool:
        """The generic selector fields; families override to interpret
        their ``axes`` filters."""
        if criteria.families and design.family not in criteria.families:
            return False
        if criteria.collections and design.collection not in criteria.collections:
            return False
        if criteria.labels and design.label not in criteria.labels:
            return False
        if criteria.products and design.relative_dir not in criteria.products:
            return False
        return True


# -- the adapter registry -------------------------------------------------------


_ADAPTERS: dict[str, FamilyAdapter] = {}


def register_adapter(adapter: FamilyAdapter) -> None:
    """Register (or replace) one family's adapter."""
    if not adapter.family:
        raise ValueError("adapter must declare its family name")
    _ADAPTERS[adapter.family] = adapter


def _ensure_builtin() -> None:
    # Imported lazily: the adapter modules import design types from here,
    # so the dependency direction models -> database stays one-way.
    if _ADAPTERS:
        return
    from stellariso.models.mist.design import MistAdapter
    from stellariso.models.parsec.design import ParsecAdapter

    register_adapter(MistAdapter())
    register_adapter(ParsecAdapter())


def adapter_for(family: str) -> FamilyAdapter:
    _ensure_builtin()
    try:
        return _ADAPTERS[family]
    except KeyError:
        raise UnsupportedModelError(
            f"no family adapter registered for {family!r}; "
            f"registered families: {sorted(_ADAPTERS)}"
        ) from None


def adapter_families() -> tuple[str, ...]:
    _ensure_builtin()
    return tuple(_ADAPTERS)
