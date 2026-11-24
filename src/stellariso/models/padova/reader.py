"""Parsers for the two legacy Padova VizieR isochrone archives.

Two fixed-width layouts, one per release, both defined byte-by-byte by
their catalog ReadMes (the files carry no comment headers):

- padova/2000 (Girardi et al. 2000, VizieR J/A+AS/141/371):
  ``isochron.dat`` (Lrecl 142) holds every isochrone of the grid — the
  Overshoot, Z, and age columns carry the grid axes per row — and
  ``isochsum.dat`` (Lrecl 94) holds the same grid's characteristic
  points with the source's G1 stage labels (TO, RGBb, RGBt, BHeb, EHeb,
  1TP, AGBt, Cb, ...), which anchor the unified phase classification.
- padova/1994 (Bertelli et al. 1994, VizieR J/A+AS/106/275):
  ``table1``..``table6`` (Lrecl 106), one file per published (Z, Y);
  the rows state neither composition nor any header, so each table's
  (Z, Y) comes from the catalog ReadMe's documented file list and the
  canonical file names are required.

All parsing is literal fixed-width slicing at the ReadMe byte offsets;
nothing is inferred from file names beyond the 1994 tables' documented
composition list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip
import os
from pathlib import Path
from typing import Any, TextIO

from astropy.table import Table
import numpy as np

from stellariso.exceptions import DataIntegrityError, UnrecognizedFormatError
from stellariso.native import NativeTable

__all__ = [
    "SALPETER_ALPHA",
    "STAGE_ANCHOR_ALIASES",
    "TABLE_COMPOSITIONS_1994",
    "Padova1994File",
    "Padova2000File",
    "PadovaIsochronBlock",
    "PadovaTableBlock",
    "open_padova_text",
    "parse_padova1994",
    "parse_padova2000",
    "parse_padova2000_summary",
    "read_data_lines",
    "sniff_layout",
]

#: Salpeter IMF slope the FLUM integral assumes (both ReadMes' notes)
SALPETER_ALPHA = 2.35

#: (Z, Y) per canonical 1994 table, from the catalog ReadMe's file list
TABLE_COMPOSITIONS_1994: dict[str, tuple[float, float]] = {
    "table1": (0.0004, 0.23),
    "table2": (0.001, 0.23),
    "table3": (0.004, 0.24),
    "table4": (0.008, 0.25),
    "table5": (0.02, 0.28),
    "table6": (0.05, 0.352),
}

# -- fixed-width layouts (0-based slices of the ReadMes' 1-based bytes) --------

_ISOCHRON_2000_FIELDS: tuple[tuple[str, slice], ...] = (
    ("Overshoot", slice(0, 1)),
    ("Z", slice(2, 9)),
    ("age", slice(10, 19)),
    ("log(age)", slice(20, 25)),
    ("Mini", slice(26, 36)),
    ("Mact", slice(37, 43)),
    ("logL", slice(44, 51)),
    ("logTeff", slice(52, 58)),
    ("logg", slice(59, 66)),
    ("Mbol", slice(67, 73)),
    ("UMAG", slice(74, 80)),
    ("BMAG", slice(81, 87)),
    ("VMAG", slice(88, 94)),
    ("RMAG", slice(95, 101)),
    ("IMAG", slice(102, 108)),
    ("JMAG", slice(109, 115)),
    ("HMAG", slice(116, 122)),
    ("KMAG", slice(123, 130)),
    ("FLUM", slice(131, 142)),
)

_ISOSCHSUM_FIELDS: tuple[tuple[str, slice], ...] = (
    ("Overshoot", slice(0, 1)),
    ("Z", slice(2, 9)),
    ("age", slice(10, 19)),
    ("log(age)", slice(20, 25)),
    ("Mini", slice(26, 32)),
    ("Stage", slice(85, 89)),
)

_TABLE_1994_FIELDS: tuple[tuple[str, slice], ...] = (
    ("log(Age)", slice(2, 8)),
    ("M", slice(10, 17)),
    ("log(Teff)", slice(19, 24)),
    ("Mbol", slice(25, 31)),
    ("V", slice(32, 38)),
    ("(U-B)", slice(40, 45)),
    ("(B-V)", slice(47, 52)),
    ("(V-R)", slice(54, 59)),
    ("(V-I)", slice(61, 66)),
    ("(V-J)", slice(68, 73)),
    ("(V-H)", slice(75, 80)),
    ("(V-K)", slice(82, 87)),
    ("FLUM", slice(88, 99)),
    ("Mwind", slice(101, 106)),
)

# stage labels of isochsum.dat that are boundaries of the coarse unified
# stages; the interior markers (Te-m, Te-M, L-M, L-m, Xc=0, Yc=0, Bhe,
# LpT, ZAMS, ZAHB, F) are not
STAGE_ANCHOR_ALIASES: tuple[tuple[str, ...], ...] = (
    ("TO",),
    ("RGBb", "Brg"),
    ("RGBt", "Tip", "BHeb"),
    ("EHeb",),
    ("1TP",),
)


def open_padova_text(source: str | os.PathLike | TextIO) -> tuple[TextIO, bool]:
    """Open a padova archive file (plain or ``.gz``) as ASCII text."""
    if hasattr(source, "read"):
        return source, False
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="ascii", errors="replace"), True
    return open(path, encoding="ascii", errors="replace"), False


def read_data_lines(source: str | os.PathLike | TextIO) -> list[str]:
    """The file's non-empty lines, as text, without parsing."""
    fh, opened = open_padova_text(source)
    try:
        return [line for line in fh.read().splitlines() if line.strip()]
    finally:
        if opened:
            fh.close()


def _parse_float(text: str) -> float:
    return float(text)


def _parse_cell(text: str, field: str, sl: slice, row: int) -> float:
    """Parse one fixed-width cell, failing with its exact file location."""
    try:
        return float(text)
    except ValueError as exc:
        raise DataIntegrityError(
            f"row {row}: field {field!r} "
            f"(bytes {sl.start + 1}-{sl.stop}) does not parse as a "
            f"number: {text!r}"
        ) from exc


def _rows_to_table(
    lines: list[str], fields: list[tuple[str, slice]], first_row: int
) -> Table:
    data = np.empty((len(lines), len(fields)), dtype=np.float64)
    for r, line in enumerate(lines):
        for c, (name, sl) in enumerate(fields):
            data[r, c] = _parse_cell(line[sl], name, sl, first_row + r + 1)
    return Table(data, names=[name for name, _ in fields])


# -- layout sniffing -------------------------------------------------------------


def sniff_layout(lines: list[str]) -> str | None:
    """Classify data lines as ``"2000"``, ``"1994"``, or ``None``."""
    if not lines:
        return None
    head = lines[0]
    try:
        if len(head) >= 131 and float(head[131:142]) and float(head[26:36]):
            return "2000"
    except ValueError:
        pass
    try:
        if len(head) >= 102 and float(head[88:99]) and float(head[2:8]):
            return "1994"
    except ValueError:
        pass
    return None


def _strip_gz(name: str) -> str:
    return name.removesuffix(".gz")


def recognize_padova(source: str | os.PathLike | TextIO) -> bool:
    """Cheap sniff: does this source look like a padova archive table?

    Reads the first data line only. A ``.gz`` file whose decompressed
    twin sits next to it is not claimed (the twin is the canonical read
    target; claiming both would read the same isochrones twice).
    """
    try:
        if not hasattr(source, "read"):
            path = Path(source)
            if path.suffix == ".gz" and (path.parent / path.stem).exists():
                return False
        lines = read_data_lines(source)[:1]
        return sniff_layout(lines) is not None
    except (OSError, UnicodeDecodeError):
        return False


# -- padova/2000 -----------------------------------------------------------------


@dataclass
class PadovaIsochronBlock:
    """One isochrone of ``isochron.dat``: one (Overshoot, Z, age) point."""

    overshoot: int
    z: float
    age: float
    log_age: float
    row_start: int  # into the compacted native table
    row_stop: int  # exclusive


@dataclass
class Padova2000File:
    """One parsed 2000-layout file: table, blocks, and header facts."""
    native: NativeTable
    blocks: tuple[PadovaIsochronBlock, ...]
    facts: dict[str, Any] = field(default_factory=dict)


def parse_padova2000(source: str | os.PathLike | TextIO) -> Padova2000File:
    """Parse ``isochron.dat`` (the padova/2000 isochrone table)."""
    lines = read_data_lines(source)
    if sniff_layout(lines) != "2000":
        raise UnrecognizedFormatError(
            "not a padova/2000 isochron.dat table (fixed-width, Lrecl 142, "
            "FLUM at bytes 132-142)"
        )
    table = _rows_to_table(lines, _ISOCHRON_2000_FIELDS, 0)

    blocks: list[PadovaIsochronBlock] = []
    start = 0
    for i in range(1, len(lines) + 1):
        changed = i == len(lines) or (
            lines[i][0] != lines[start][0]
            or lines[i][2:9] != lines[start][2:9]
            or lines[i][10:19] != lines[start][10:19]
        )
        if changed:
            log_ages = np.unique(np.round(table["log(age)"][start:i], decimals=6))
            if len(log_ages) != 1:
                raise DataIntegrityError(
                    f"isochrone block at row {start + 1} spans {len(log_ages)} "
                    f"distinct log(age) values: {log_ages[:5]}"
                )
            blocks.append(
                PadovaIsochronBlock(
                    overshoot=int(table["Overshoot"][start]),
                    z=float(table["Z"][start]),
                    age=float(table["age"][start]),
                    log_age=float(log_ages[0]),
                    row_start=start,
                    row_stop=i,
                )
            )
            start = i

    keys = {(b.overshoot, b.z, b.log_age) for b in blocks}
    if len(keys) != len(blocks):
        raise DataIntegrityError(
            "isochron.dat repeats an (Overshoot, Z, log(age)) grid point"
        )
    facts = {
        "release": "2000",
        "n_isochrones": len(blocks),
        "z_values": tuple(sorted({b.z for b in blocks})),
        "overshoot_values": tuple(sorted({b.overshoot for b in blocks})),
    }
    native = NativeTable(
        table=table,
        header=(),
        metadata=facts,
        block_metadata=tuple(
            {"overshoot": b.overshoot, "z": b.z, "log_age": b.log_age}
            for b in blocks
        ),
    )
    return Padova2000File(native=native, blocks=tuple(blocks), facts=facts)


def parse_padova2000_summary(
    source: str | os.PathLike | TextIO,
) -> dict[tuple[int, float, float], dict[str, float]]:
    """Parse ``isochsum.dat`` into ``{(overshoot, z, log_age): {stage: Mini}}``.

    Characteristic points whose stage label is not a coarse-stage
    boundary anchor are dropped here (the backend's boundary chain uses
    only the anchor labels). Summary isochrones with no counterpart in
    ``isochron.dat`` (the archive carries two) are simply never looked
    up.
    """
    lines = read_data_lines(source)
    if not lines or len(lines[0]) < 89:
        raise UnrecognizedFormatError(
            "not a padova/2000 isochsum.dat summary table (fixed-width, "
            "Lrecl 94, Stage at bytes 86-89)"
        )
    anchors: dict[tuple[int, float, float], dict[str, float]] = {}
    boundary_labels = {label for aliases in STAGE_ANCHOR_ALIASES for label in aliases}
    for i, line in enumerate(lines):
        try:
            overshoot = int(line[0])
            z = float(line[2:9])
            log_age = float(line[20:25])
            mini = float(line[26:32])
        except ValueError as exc:
            raise DataIntegrityError(
                f"isochsum.dat row {i + 1} does not parse: {exc}"
            ) from exc
        stage = line[85:89].strip()
        if stage not in boundary_labels:
            continue
        anchors.setdefault((overshoot, z, log_age), {})[stage] = mini
    return anchors


# -- padova/1994 ------------------------------------------------------------------


@dataclass
class PadovaTableBlock:
    """One isochrone of a 1994 table: one log(age) value."""

    log_age: float
    row_start: int
    row_stop: int  # exclusive


@dataclass
class Padova1994File:
    """One parsed 1994-layout file: table, blocks, and header facts."""
    native: NativeTable
    blocks: tuple[PadovaTableBlock, ...]
    facts: dict[str, Any] = field(default_factory=dict)


def parse_padova1994(source: str | os.PathLike | TextIO) -> Padova1994File:
    """Parse one ``tableN`` file of the padova/1994 archive.

    The file states neither its composition nor any header, so the
    canonical file name is required: the (Z, Y) assignment comes from
    the catalog ReadMe's documented file list.
    """
    if hasattr(source, "read") and not hasattr(source, "name"):
        raise UnrecognizedFormatError(
            "padova/1994 tables require their canonical file name "
            "(table1..table6): the composition is assigned from the "
            "catalog ReadMe's file list, and the files state none of it"
        )
    name = _strip_gz(Path(getattr(source, "name", source)).name)
    if name not in TABLE_COMPOSITIONS_1994:
        raise UnrecognizedFormatError(
            f"{name!r} is not a canonical padova/1994 table name "
            f"(table1..table6); the composition assignment requires the "
            "catalog's documented file names"
        )
    z, y = TABLE_COMPOSITIONS_1994[name]
    lines = read_data_lines(source)
    if sniff_layout(lines) != "1994":
        raise UnrecognizedFormatError(
            f"{name} is not a padova/1994 isochrone table (fixed-width, "
            "Lrecl 106, FLUM at bytes 89-99)"
        )
    table = _rows_to_table(lines, _TABLE_1994_FIELDS, 0)

    blocks: list[PadovaTableBlock] = []
    start = 0
    for i in range(1, len(lines) + 1):
        changed = i == len(lines) or lines[i][2:8] != lines[start][2:8]
        if changed:
            ages = np.unique(np.round(table["log(Age)"][start:i], decimals=6))
            if len(ages) != 1:
                raise DataIntegrityError(
                    f"isochrone block at row {start + 1} of {name} spans "
                    f"{len(ages)} distinct log(Age) values: {ages[:5]}"
                )
            blocks.append(
                PadovaTableBlock(
                    log_age=float(ages[0]), row_start=start, row_stop=i
                )
            )
            start = i
    ages_seen = [b.log_age for b in blocks]
    if len(set(ages_seen)) != len(ages_seen):
        raise DataIntegrityError(
            f"{name} repeats a log(Age) isochrone in a non-contiguous block"
        )

    facts = {
        "release": "1994",
        "table": name,
        "initial_z": z,
        "initial_helium": y,
        "n_isochrones": len(blocks),
    }
    native = NativeTable(
        table=table,
        header=(),
        metadata=facts,
        block_metadata=tuple({"log_age": b.log_age} for b in blocks),
    )
    return Padova1994File(native=native, blocks=tuple(blocks), facts=facts)
