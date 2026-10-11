"""Parser for MIST theoretical isochrone files (``.iso``).

The parser is deliberately literal: it walks the file's comment structure,
uses the per-block ``number of EEPs, cols`` lines as block boundaries (each
block also repeats the column-index and column-name lines), and validates
what it reads against what the file claims about itself. All facts are taken
from the file content, never from the filename.

Format (verified against interp-form output, MIST version 1.2 / MESA r7503)::

    # MIST version number  = 1.2
    # MESA revision number =     7503
    # ----
    #  Yinit        Zinit   [Fe/H]   [a/Fe]  v/vcrit
    # 0.2514  1.88066E-03    -1.00     0.00     0.40
    # ----
    # number of isochrones =     2
    # ----
    # number of EEPs, cols =  1515   79     <- block 1 starts
    #   1    2    ... (column index line)
    # EEP   log10_isochrone_age_yr  ...     <- column name line
    <1515 whitespace-separated data rows>
    <blank lines>
    # number of EEPs, cols =  1467   79     <- block 2
    ...
"""

from __future__ import annotations

import gzip
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import numpy as np
from astropy.table import Table

from ...exceptions import DataIntegrityError, UnrecognizedFormatError
from ...native import NativeTable

__all__ = ["MistFile", "parse_mist_iso", "open_mist_text"]

_VERSION_RE = re.compile(r"MIST version number\s*=\s*(\S+)")
_MESA_RE = re.compile(r"MESA revision number\s*=\s*(\S+)")
_COMPOSITION_NAMES = ("Yinit", "Zinit", "[Fe/H]", "[a/Fe]", "v/vcrit")
_N_ISO_RE = re.compile(r"number of isochrones\s*=\s*(\d+)")
_BLOCK_RE = re.compile(r"number of EEPs, cols\s*=\s*(\d+)\s+(\d+)")


@dataclass
class MistBlock:
    """One isochrone block of a MIST file.

    ``row_start``/``row_stop`` index into the compacted native table (all
    data rows of the file, block after block); ``line_start``/``line_stop``
    index the original file lines and are used only during validation.
    """

    n_eeps: int  # as stated by the block header line
    n_cols: int
    header_lines: tuple[str, ...]  # the three block header lines
    line_start: int  # first data line in the file
    line_stop: int  # exclusive
    row_start: int = -1  # first row in the native table (filled by parser)
    row_stop: int = -1  # exclusive

    @property
    def n_rows(self) -> int:
        return self.line_stop - self.line_start


@dataclass
class MistFile:
    """Everything parsed from one MIST ``.iso`` file."""

    native: NativeTable
    blocks: tuple[MistBlock, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)


def open_mist_text(source: str | os.PathLike | TextIO) -> tuple[TextIO, bool]:
    """Open ``.iso`` or ``.iso.gz`` sources as ASCII text; caller closes."""
    if hasattr(source, "read"):
        return source, False
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="ascii", errors="replace"), True
    return open(path, mode="r", encoding="ascii", errors="replace"), False


def parse_mist_iso(source: str | os.PathLike | TextIO) -> MistFile:
    """Parse a MIST theoretical isochrone file into native form."""
    fh, opened = open_mist_text(source)
    try:
        lines = fh.read().splitlines()
    finally:
        if opened:
            fh.close()

    facts: dict[str, Any] = {}
    header_lines: list[str] = []
    blocks: list[MistBlock] = []
    column_names: list[str] | None = None

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.startswith("#"):
            if line.strip():
                raise UnrecognizedFormatError(
                    f"unexpected data line {i + 1} outside any isochrone block: "
                    f"{line[:60]!r}"
                )
            i += 1
            continue

        stripped = line.lstrip("# ").strip()

        m = _VERSION_RE.search(stripped)
        if m and "mist_version" not in facts:
            facts["mist_version"] = m.group(1)
            header_lines.append(line)
            i += 1
            continue
        m = _MESA_RE.search(stripped)
        if m and "mesa_revision" not in facts:
            facts["mesa_revision"] = m.group(1)
            header_lines.append(line)
            i += 1
            continue
        m = _N_ISO_RE.search(stripped)
        if m:
            facts["n_isochrones"] = int(m.group(1))
            header_lines.append(line)
            i += 1
            continue

        m = _BLOCK_RE.search(stripped)
        if m:
            block = _parse_block(lines, i, m)
            if column_names is None:
                column_names = block_column_names(block)
            else:
                other = block_column_names(block)
                if other != column_names:
                    raise DataIntegrityError(
                        "column names differ between isochrone blocks: "
                        f"{column_names[:5]}... vs {other[:5]}..."
                    )
            blocks.append(block)
            i = block.line_stop
            continue

        # composition pair: names line then values line
        if stripped.split() == list(_COMPOSITION_NAMES):
            values = lines[i + 1].lstrip("#").split()
            if len(values) != 5:
                raise DataIntegrityError(
                    f"composition values line does not carry 5 values: {lines[i+1]!r}"
                )
            facts["yinit"], facts["zinit"] = float(values[0]), float(values[1])
            facts["feh"], facts["afe"], facts["vvcrit"] = (
                float(values[2]),
                float(values[3]),
                float(values[4]),
            )
            header_lines.extend([line, lines[i + 1]])
            i += 2
            continue

        header_lines.append(line)
        i += 1

    _validate(facts, blocks, column_names)

    data = np.empty(
        (sum(b.n_rows for b in blocks), len(column_names)), dtype=np.float64
    )
    row = 0
    for b in blocks:
        b.row_start = row
        for r in range(b.line_start, b.line_stop):
            parts = lines[r].split()
            if len(parts) != b.n_cols:
                raise DataIntegrityError(
                    f"row {r + 1} has {len(parts)} fields, expected {b.n_cols}"
                )
            data[row] = [float(x) for x in parts]
            row += 1
        b.row_stop = row

    table = Table(data, names=list(column_names))
    block_metadata = tuple(
        {"n_eeps": b.n_eeps, "n_cols": b.n_cols} for b in blocks
    )
    native = NativeTable(
        table=table,
        header=tuple(header_lines),
        metadata=dict(facts),
        block_metadata=block_metadata,
    )
    return MistFile(native=native, blocks=tuple(blocks), facts=facts)


def _parse_block(lines: list[str], header_idx: int, m: re.Match) -> MistBlock:
    n_eeps, n_cols = int(m.group(1)), int(m.group(2))
    index_line, names_line = lines[header_idx + 1], lines[header_idx + 2]
    if not index_line.lstrip("#").split()[0].isdigit():
        raise DataIntegrityError(
            f"expected column-index line after 'number of EEPs, cols' at line "
            f"{header_idx + 2}, got {index_line[:50]!r}"
        )
    names = names_line.lstrip("#").split()
    if len(names) != n_cols:
        raise DataIntegrityError(
            f"column-name line carries {len(names)} names, header claims "
            f"{n_cols} columns"
        )
    j = header_idx + 3
    n = len(lines)
    start = j
    while j < n and (not lines[j].startswith("#")) and lines[j].strip():
        j += 1
    # tolerate trailing blank lines inside the block count only if a new
    # block or EOF follows
    while j < n and not lines[j].strip():
        j += 1
    stop = start + n_eeps
    if stop > j:
        raise DataIntegrityError(
            f"isochrone block at line {header_idx + 1} declares {n_eeps} rows "
            f"but only {j - start} are present"
        )
    return MistBlock(
        n_eeps=n_eeps,
        n_cols=n_cols,
        header_lines=(lines[header_idx], index_line, names_line),
        line_start=start,
        line_stop=stop,
    )


def block_column_names(block: MistBlock) -> list[str]:
    return block.header_lines[2].lstrip("#").split()


def _validate(facts: dict, blocks: list[MistBlock], column_names) -> None:
    required = ("mist_version", "n_isochrones", "yinit", "zinit", "feh")
    missing = [k for k in required if k not in facts]
    if missing:
        raise UnrecognizedFormatError(
            f"file does not carry the expected MIST header facts: missing {missing}; "
            "not a MIST theoretical isochrone file?"
        )
    if not blocks:
        raise UnrecognizedFormatError("no isochrone blocks found")
    if facts["n_isochrones"] != len(blocks):
        raise DataIntegrityError(
            f"header declares {facts['n_isochrones']} isochrones, "
            f"found {len(blocks)} blocks"
        )
    for name in ("EEP", "log10_isochrone_age_yr", "initial_mass"):
        if name not in column_names:
            raise UnrecognizedFormatError(
                f"required column {name!r} absent from column-name line"
            )
