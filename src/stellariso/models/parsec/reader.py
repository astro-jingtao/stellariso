"""Parser for Padova/PARSEC CMD isochrone tables.

The column layout follows the "TABLES OF ISOCHRONES" section of the Girardi
isochrone readme (log(age/yr), M_ini, M_act, logL/Lo, logTe, logG, Mbol,
magnitudes, IMF integral) with the CMD 3.9 updates (``int_IMF`` replacing
FLUM; ``C/O``, ``M_hec``, ``logMdot``, ``label`` added). The parser is
column-name driven — names are read from the file's own column-name line, so
column reordering between CMD versions does not silently misread data.

Blocks: each isochrone is introduced by comment line(s) stating its age and
composition (the readme's "HEADER LINE"). The reader starts a new block at
every comment line that follows data rows, and cross-checks each block
against the ``log(age/yr)`` column (one age per block, loud error otherwise).
"""

from __future__ import annotations

import gzip
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import numpy as np
from astropy.table import Table

from ...exceptions import DataIntegrityError, UnrecognizedFormatError
from ...native import NativeTable

__all__ = ["ParsecFile", "parse_parsec_cmd", "open_parsec_text"]

_RELEASE_RE = re.compile(r"isochrones based on PARSEC release\s+(.+?)\s*$", re.M)
_ETA_RE = re.compile(r"Reimers mass loss with efficiency eta=(\S+)")
_PHOTSYS_RE = re.compile(r"Photometric system:\s*<i>(.*?)</i>", re.S)
_BLOCK_Z_RE = re.compile(r"\bZ=([0-9.eE+-]+)")
_BLOCK_Y_RE = re.compile(r"\bY=([0-9.eE+-]+)")
_BLOCK_X_RE = re.compile(r"\bX=([0-9.eE+-]+)")


@dataclass
class ParsecBlock:
    """One isochrone block (extents index the compacted native table)."""

    header_lines: tuple[str, ...]
    row_start: int
    row_stop: int
    z: float | None = None
    y: float | None = None
    x: float | None = None

    @property
    def n_rows(self) -> int:
        return self.row_stop - self.row_start


@dataclass
class ParsecFile:
    native: NativeTable
    blocks: tuple[ParsecBlock, ...] = ()
    facts: dict = field(default_factory=dict)


def open_parsec_text(source: str | os.PathLike | TextIO) -> tuple[TextIO, bool]:
    if hasattr(source, "read"):
        return source, False
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8", errors="replace"), True
    return open(path, mode="r", encoding="utf-8", errors="replace"), False


def _looks_like_columns(tokens: list[str]) -> bool:
    return "M_ini" in tokens and "M_act" in tokens


class _BlockAccumulator:
    """Collects (header lines, data rows) groups in file order."""

    def __init__(self) -> None:
        self.groups: list[dict] = []
        self._current: dict | None = None

    def comment(self, line: str) -> None:
        if self._current is None or self._current["rows"]:
            self._current = {"hdr": [line], "rows": []}
            self.groups.append(self._current)
        else:
            self._current["hdr"].append(line)

    def data(self, parts: list[str]) -> None:
        if self._current is None:
            self._current = {"hdr": [], "rows": []}
            self.groups.append(self._current)
        self._current["rows"].append(parts)

    def finish(self) -> list[dict]:
        return [g for g in self.groups if g["rows"]]


def parse_parsec_cmd(source: str | os.PathLike | TextIO) -> ParsecFile:
    fh, opened = open_parsec_text(source)
    try:
        lines = fh.read().splitlines()
    finally:
        if opened:
            fh.close()

    header_lines: list[str] = []
    columns: list[str] | None = None
    acc = _BlockAccumulator()

    for line in lines:
        if line.startswith("#"):
            if columns is None:
                tokens = line.lstrip("#").split()
                if _looks_like_columns(tokens):
                    columns = tokens
                else:
                    header_lines.append(line)
            else:
                acc.comment(line)
            continue
        if not line.strip():
            continue
        if columns is None:
            raise UnrecognizedFormatError(
                "data rows before any column-name line; not a CMD isochrone table?"
            )
        acc.data(line.split())

    if columns is None:
        raise UnrecognizedFormatError(
            "no column-name line (M_ini/M_act signature) found; "
            "not a CMD isochrone table?"
        )
    for name in ("M_ini", "logTe", "logG"):
        if name not in columns:
            raise UnrecognizedFormatError(
                f"required column {name!r} absent from column-name line"
            )
    age_name = "log(age/yr)"
    if age_name not in columns:
        raise UnrecognizedFormatError(f"column {age_name!r} not found")
    age_col = columns.index(age_name)

    groups = acc.finish()
    arr = np.array(
        [[float(v) for v in row] for g in groups for row in g["rows"]],
        dtype=np.float64,
    )
    if arr.size == 0:
        raise UnrecognizedFormatError("no data rows")

    blocks: list[ParsecBlock] = []
    ages: list[float] = []
    row_cursor = 0
    for g in groups:
        start, stop = row_cursor, row_cursor + len(g["rows"])
        row_cursor = stop
        rows = arr[start:stop]
        for j, parts in enumerate(g["rows"]):
            if len(parts) != len(columns):
                raise DataIntegrityError(
                    f"row {start + j} has {len(parts)} fields, column line "
                    f"declares {len(columns)}"
                )
        unique = np.unique(np.round(rows[:, age_col], 6))
        if len(unique) != 1:
            raise DataIntegrityError(
                f"isochrone block at rows {start}:{stop} spans "
                f"{len(unique)} distinct ages"
            )
        text = "\n".join(g["hdr"])
        blocks.append(
            ParsecBlock(
                header_lines=tuple(g["hdr"]),
                row_start=start,
                row_stop=stop,
                z=_first(_BLOCK_Z_RE, text),
                y=_first(_BLOCK_Y_RE, text),
                x=_first(_BLOCK_X_RE, text),
            )
        )
        ages.append(float(unique[0]))

    header_text = "\n".join(header_lines)
    facts: dict = {"ages": tuple(ages)}
    m = _RELEASE_RE.search(header_text)
    facts["release"] = m.group(1).strip() if m else None
    m = _ETA_RE.search(header_text)
    facts["eta_reimers"] = float(m.group(1)) if m else None
    m = _PHOTSYS_RE.search(header_text)
    facts["photsys"] = m.group(1).strip() if m else None

    table = Table(arr, names=list(columns))
    native = NativeTable(
        table=table,
        header=tuple(header_lines),
        metadata={k: v for k, v in facts.items() if k != "ages"},
        block_metadata=tuple(
            {"log_age": a, "z": b.z, "y": b.y, "x": b.x}
            for a, b in zip(ages, blocks)
        ),
    )
    return ParsecFile(native=native, blocks=tuple(blocks), facts=facts)


def _first(regex: re.Pattern, text: str) -> float | None:
    m = regex.search(text)
    return float(m.group(1)) if m else None
