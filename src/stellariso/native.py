"""Native layer: a faithful representation of one upstream isochrone file.

The native table preserves exactly what the file contains — column names and
order, numeric values as parsed, the comment/header block, and any metadata
the backend extracted from it. Nothing is renamed, converted, or filled in.
The unified layer (``stellariso.unified``) is built on top of this, never
instead of it.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping

import numpy as np
from astropy.table import Table

__all__ = ["NativeTable"]


@dataclasses.dataclass(frozen=True)
class NativeTable:
    """One parsed upstream table plus its verbatim header material.

    Attributes
    ----------
    table
        ``astropy.table.Table`` of the data rows, columns in file order,
        carrying no added or renamed columns.
    columns
        Column names as they appear in the file (shortcut for
        ``table.colnames``).
    header
        Verbatim header/comment lines of the file, in order, including their
        comment markers.
    metadata
        Structured key/value pairs the backend extracted from the header
        (version strings, composition values, block counts). Keys are the
        backend's own; values are what the file states — never inferred.
    provenance_keys
        Free-form notes keyed by the backend, e.g. per-block metadata such as
        each isochrone block's stated row count.
    """

    table: Table
    header: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    block_metadata: tuple[Mapping[str, Any], ...] = ()

    @property
    def columns(self) -> list[str]:
        return self.table.colnames

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", tuple(self.header))
        object.__setattr__(
            self, "block_metadata", tuple(dict(b) for b in self.block_metadata)
        )
        if not isinstance(self.table, Table):
            raise TypeError("native.table must be an astropy Table")

    def __getitem__(self, name: str) -> np.ndarray:
        """Native column access by the file's own column name."""
        return np.asarray(self.table[name])

    def __contains__(self, name: str) -> bool:
        return name in self.table.colnames

    def __len__(self) -> int:
        return len(self.table)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NativeTable):
            return NotImplemented
        return (
            self.columns == other.columns
            and len(self.table) == len(other.table)
            and all(np.array_equal(self.table[c], other.table[c]) for c in self.columns)
            and self.header == other.header
            and dict(self.metadata) == dict(other.metadata)
        )

    def to_table(self) -> Table:
        """Return the native table itself (not a copy of the data)."""
        return self.table
