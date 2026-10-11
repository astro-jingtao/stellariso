"""PARSEC v1.2S stellar-track reader (official archive format).

One plain-text file per initial mass (see the official readme of the
PARSEC v1.2S track database). Files come inside per-composition zips
(e.g. ``Z0.0001Y0.249OUTA1.74_F7_M001.200.DAT``); the initial mass and
the composition are stated by the file and zip names, not by columns.
``*ADD.DAT`` files are discarded (official instruction) and ``*.HB.DAT``
files (post-helium-flash horizontal-branch tracks) are parsed separately:
their PHASE numbering restarts with its own meaning.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TextIO

import numpy as np
from astropy.table import Table

from stellariso.core import ModelIdentity
from stellariso.exceptions import DataIntegrityError, UnrecognizedFormatError
from stellariso.native import NativeTable
from stellariso.provenance import Provenance
from stellariso.registry import (
    field_spec_dict,
    phase_mapping,
    references,
    resolve_parameters,
)
from stellariso.unified import UnifiedView

__all__ = [
    "ParsecTrack",
    "ParsecTrackSet",
    "parse_parsec_tracks",
    "parse_parsec_track_file",
    "recognize_parsec_tracks",
]

_TRACK_COLUMNS = (
    "MODELL MASS AGE LOG_L LOG_TE LOG_R LOG_RAT M_CORE_HE M_CORE_C "
    "H_CEN HE_CEN C_cen O_cen LX LY LC LNEUTR L_GRAV H_SUP HE_SUP C_SUP "
    "N_SUP O_SUP PHASE"
).split()

_FILE_RE = re.compile(r"_M(\d+(?:\.\d+)?)(ADD)?(\.HB)?\.DAT$", re.IGNORECASE)
_ZY_RE = re.compile(r"Z(\d+(?:\.\d+)?)Y(\d+(?:\.\d+)?)")

# IAU 2015 nominal solar mass parameter; CODATA 2018 G (cgs)
_M_SUN_G = 1.98847e33
_G_CGS = 6.67430e-8

_FIELD_SPECS = field_spec_dict("parsec", "tracks_v12s")
_STANDARD_PHASE = phase_mapping("parsec", "tracks_v12s")
_HB_PHASE = phase_mapping("parsec", "tracks_v12s", variant="hb")


def _log_g(native: NativeTable) -> np.ndarray:
    mass_g = np.asarray(native["MASS"], dtype=float) * _M_SUN_G
    r_cm = np.power(10.0, np.asarray(native["LOG_R"], dtype=float))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log10(_G_CGS * mass_g / (r_cm**2))


def _phase_computation(mapping):
    def compute(native: NativeTable) -> np.ndarray:
        codes = np.floor(np.asarray(native["PHASE"], dtype=float) + 1e-9)
        return mapping(codes)

    return compute


_COMPUTATIONS_STANDARD = {
    "phase": _phase_computation(_STANDARD_PHASE),
    "log_surface_gravity": _log_g,
}
_COMPUTATIONS_HB = {
    "phase": _phase_computation(_HB_PHASE),
    "log_surface_gravity": _log_g,
}


@dataclass(frozen=True)
class ParsecTrack:
    """One track: one file, one initial mass, its native table and view."""

    native: NativeTable
    initial_mass: float
    kind: str  # "standard" | "hb"
    source_name: str

    @property
    def computations(self) -> dict:
        return _COMPUTATIONS_HB if self.kind == "hb" else _COMPUTATIONS_STANDARD

    @property
    def unified(self) -> UnifiedView:
        return UnifiedView(
            self.native,
            _FIELD_SPECS,
            computations=self.computations,
            constants={"initial_mass": self.initial_mass},
        )

    @property
    def log_age_range(self) -> tuple[float, float]:
        """log10 of the track's first and last age (years)."""
        ages = np.log10(np.asarray(self.native["AGE"], dtype=float))
        return float(ages[0]), float(ages[-1])


class ParsecTrackSet:
    """All tracks of one composition: standard tracks, HB tracks, discards."""

    def __init__(
        self,
        tracks: tuple[ParsecTrack, ...],
        hb_tracks: tuple[ParsecTrack, ...],
        discarded: tuple[str, ...],
        initial_z: float | None,
        initial_helium: float | None,
        provenance: Provenance | None = None,
    ):
        self._tracks = tuple(sorted(tracks, key=lambda t: t.initial_mass))
        self._hb_tracks = tuple(sorted(hb_tracks, key=lambda t: t.initial_mass))
        self.discarded = tuple(discarded)
        self.initial_z = initial_z
        self.initial_helium = initial_helium
        self.provenance = (
            provenance
            if provenance is not None and provenance.scientific_references
            else _with_references(provenance)
        )

    @property
    def tracks(self) -> tuple[ParsecTrack, ...]:
        return self._tracks

    @property
    def hb_tracks(self) -> tuple[ParsecTrack, ...]:
        return self._hb_tracks

    def __len__(self) -> int:
        return len(self._tracks)

    def __iter__(self) -> Iterator[ParsecTrack]:
        return iter(self._tracks)

    @property
    def identity(self) -> ModelIdentity:
        physics = None
        if self.initial_z is not None and self.initial_helium is not None:
            physics = f"Z{self.initial_z}Y{self.initial_helium}"
        return ModelIdentity(
            family="parsec",
            release="v1.2S",
            product="stellar_tracks",
            physics_configuration=physics,
            description=(
                "PARSEC v1.2S stellar evolutionary tracks from the official "
                "Padova track archive (one file per initial mass, PMS to "
                "He flash / a few thermal pulses / C ignition)"
            ),
        )

    @property
    def parameters(self) -> tuple:
        dynamic = {"initial_mass": tuple(t.initial_mass for t in self._tracks)}
        if self.initial_z is not None:
            dynamic["initial_z"] = self.initial_z
        if self.initial_helium is not None:
            dynamic["initial_helium"] = self.initial_helium
        return resolve_parameters("parsec", "tracks_v12s", dynamic)


def _with_references(provenance: Provenance | None) -> Provenance:
    return Provenance(
        data_sources=provenance.data_sources if provenance else (),
        assets=provenance.assets if provenance else (),
        source_chains=provenance.source_chains if provenance else (),
        scientific_references=references("parsec"),
        software_references=provenance.software_references if provenance else (),
        transformations=provenance.transformations if provenance else (),
    )


# -- single-file parsing -------------------------------------------------------


def parse_track_text(text: str, source_name: str) -> tuple[NativeTable, float | None, str, bool]:
    """Parse one track file's text.

    Returns ``(native, initial_mass, kind, is_add)``; ``initial_mass`` is
    ``None`` when the filename carries no recognizable mass.
    """
    lines = text.splitlines()
    if not lines:
        raise DataIntegrityError(f"{source_name}: empty track file")
    columns = lines[0].split()
    if columns != _TRACK_COLUMNS:
        raise UnrecognizedFormatError(
            f"{source_name}: column signature is not the PARSEC v1.2S track "
            f"format (expected {_TRACK_COLUMNS}, got {columns[:8]}...)"
        )
    data_lines = [l for l in lines[1:] if l.strip()]
    if not data_lines:
        raise DataIntegrityError(f"{source_name}: no data rows")

    rows = np.array([l.split() for l in data_lines], dtype=float)
    if rows.shape[1] != len(columns):
        raise DataIntegrityError(
            f"{source_name}: {rows.shape[1]} values per row, "
            f"expected {len(columns)}"
        )
    table = Table(rows, names=columns)

    mass = None
    kind = "standard"
    is_add = False
    m = _FILE_RE.search(Path(source_name).name)
    if m:
        mass = float(m.group(1))
        is_add = m.group(2) is not None
        kind = "hb" if m.group(3) else "standard"

    native = NativeTable(
        table=table,
        header=(lines[0],),
        metadata={
            "source_name": str(source_name),
            "filename_initial_mass": mass,
            "kind": kind,
            "is_add": is_add,
        },
    )
    return native, mass, kind, is_add


def parse_parsec_track_file(source: str | os.PathLike | TextIO) -> ParsecTrack:
    """Read one ``*.DAT`` track file from disk."""
    path = Path(source)
    native, mass, kind, _ = parse_track_text(
        path.read_text(encoding="ascii"), str(path)
    )
    if mass is None:
        raise DataIntegrityError(
            f"{path}: filename carries no parseable initial mass"
        )
    return ParsecTrack(
        native=native, initial_mass=mass, kind=kind, source_name=str(path)
    )


def recognize_parsec_track_file(source: str | os.PathLike) -> bool:
    try:
        first = Path(source).open(encoding="ascii").readline()
    except (OSError, UnicodeDecodeError):
        return False
    return first.split() == _TRACK_COLUMNS


# -- set parsing (zip or directory) --------------------------------------------


def _composition_of(name: str) -> tuple[float | None, float | None]:
    m = _ZY_RE.search(name)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


class _Member:
    """Uniform view of a zip member or a plain file."""

    def __init__(self, name: str, read_text):
        self.name = name
        self._read_text = read_text

    def text(self) -> str:
        return self._read_text()


def _members_of(source: Path) -> list[_Member]:
    if source.is_file() and source.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(source)
        return [
            _Member(name, lambda n=name: zf.read(n).decode("ascii"))
            for n in zf.namelist()
            if n.endswith(".DAT")
        ]
    if source.is_dir():
        return [
            _Member(str(p), p.read_text) for p in sorted(source.rglob("*.DAT"))
        ]
    raise UnrecognizedFormatError(
        f"{source}: expected a track zip file or a directory of *.DAT tracks"
    )


def parse_parsec_tracks(
    source: str | os.PathLike, provenance: Provenance | None = None
) -> ParsecTrackSet:
    """Read a PARSEC v1.2S track set from a zip archive or a directory.

    ``*ADD.DAT`` files are recorded as discarded (official instruction),
    ``*.HB.DAT`` files go into ``hb_tracks``, everything else becomes a
    standard track. Z and Y come from the file/directory naming.
    """
    root = Path(source)
    members = _members_of(root)
    if not members:
        raise UnrecognizedFormatError(f"{source}: no .DAT track files found")

    tracks, hb_tracks, discarded = [], [], []
    initial_z = initial_helium = None
    for member in members:
        z, y = _composition_of(member.name)
        if z is not None:
            initial_z, initial_helium = z, y
        native, mass, kind, is_add = parse_track_text(member.text(), member.name)
        if is_add:
            discarded.append(member.name)
            continue
        if mass is None:
            raise DataIntegrityError(
                f"{member.name}: filename carries no parseable initial mass"
            )
        track = ParsecTrack(
            native=native, initial_mass=mass, kind=kind, source_name=member.name
        )
        (hb_tracks if kind == "hb" else tracks).append(track)

    if not tracks and not hb_tracks:
        raise UnrecognizedFormatError(f"{source}: no PARSEC track data parsed")

    return ParsecTrackSet(
        tracks=tuple(tracks),
        hb_tracks=tuple(hb_tracks),
        discarded=tuple(discarded),
        initial_z=initial_z,
        initial_helium=initial_helium,
        provenance=provenance,
    )


def recognize_parsec_tracks(source: str | os.PathLike) -> bool:
    """Cheap sniff: does this zip/directory hold PARSEC v1.2S tracks?"""
    try:
        members = _members_of(Path(source))
    except (UnrecognizedFormatError, OSError, zipfile.BadZipFile):
        return False
    for member in members[:5] + members[-5:]:
        try:
            first = member.text().splitlines()[0]
        except (OSError, UnicodeDecodeError, IndexError, zipfile.BadZipFile):
            continue
        if first.split() == _TRACK_COLUMNS:
            return True
    return False
