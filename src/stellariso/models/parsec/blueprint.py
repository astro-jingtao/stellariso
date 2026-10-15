"""The declared full-acquisition blueprint for PARSEC form products.

The blueprint is the fixed, complete design of the form-computed database:
which cells will exist when the build is finished, at which parameter
values, with every field of every submission pinned. It deliberately makes
no distinction between "fine" and "coarse" products — one uniform fine
design covers every track set — and separates *design* from *fetch
order*: primary sets are fetched at full design extent, secondary sets
are fetched sparsely first (a subset of the same designed cells) and can
be completed later without redesign.

Design summary (docs/parsec-blueprint.md carries the full rationale,
including the fixed values of every non-varied field):

- Cells: one per (track set, [M/H], omega_i) combination the form
  accepts. ``omega_i`` is a dimension only where the form offers it
  (PARSEC v2.0); every other set is fixed at omega_i = 0.
- [M/H]: 0.1 dex steps over each set's full valid window, plus the exact
  window edges whenever they do not fall on the 0.1 dex grid.
- Ages: two grids per cell, archived together in the cell's directory —
  the log10 grid 6.6 to 10.13 dex step 0.02 (the current range and
  spacing, uniform for all sets), and a linear grid 0 to 4.0e6 yr step
  1.0e5 yr refining the youngest ages below 10^6.6 yr ~ 3.98 Myr.
- Everything else — IMF, photometric system, circumstellar dust,
  extinction, LPV prescription, Reimers eta, TP-cycle resolution, output
  kind — is fixed at the canonical baseline (:data:`DEFAULT_FIELDS` of
  the request layer), because none of it changes the isochrone tables
  this library consumes (the reasons are documented per field in the
  blueprint document). Every submission therefore remains the complete
  field set, and each archived acquisition record pins a payload that
  can replay the identical request.

The blueprint declares the target state; what the database actually
holds is decided by comparing it against this module
(tools/blueprint_status.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator, Mapping

from stellariso.models.parsec.cmd_form import DEFAULT_FIELDS

__all__ = [
    "MH_STEP",
    "OMEGA_VALUES",
    "LOG_AGE_GRID",
    "LINEAR_AGE_GRID",
    "SPARSE_ANCHOR_MH",
    "TRACK_SETS",
    "TrackSet",
    "Cell",
    "canonical_fields",
    "z_to_mh",
    "mh_grid",
    "mh_label",
    "expected_log_ages",
    "expected_linear_ages",
    "cells",
    "all_cells",
]

#: Composition grid step (dex) and the initial-rotation grid (omega/omega_crit;
#: 0.1 steps over the form's 0-0.99 range, plus the near-critical 0.99 which
#: is not itself a 0.1-grid point).
MH_STEP = 0.1
OMEGA_VALUES: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99)

#: The two age grids every cell carries. Log: the form's own current range
#: and the fine spacing, uniform across sets. Linear: the young-age
#: refinement below 10^6.6 yr = 3.981 Myr, handed off at 4.0 Myr (values
#: in years; 41 designed ages 0.0, 1e5, ..., 4.0e6).
LOG_AGE_GRID: tuple[str, str, str] = ("6.6", "10.13", "0.02")
LINEAR_AGE_GRID: tuple[str, str, str] = ("0.0", "4.0e6", "1.0e5")

#: Secondary-tier initial slice: anchor compositions (metal-poor, solar,
#: metal-rich) that every secondary set carries from the start; the window
#: edges join them so the valid range is pinned at both ends from day one.
SPARSE_ANCHOR_MH: tuple[float, ...] = (-1.0, 0.0, 0.3)

#: Solar reference and PARSEC enrichment law of the form itself, used to
#: convert the Z windows the form states for some COLIBRI options into
#: [M/H] window edges (docs/cmd-form.md, "Metallicity convention").
_ZX_SUN = 0.0207
_ENRICHMENT = (0.2485, 1.78)


def canonical_fields() -> dict[str, str]:
    """The fixed, non-varied values every blueprint submission carries.

    This is the request layer's own verified baseline payload verbatim:
    the blueprint fixes rather than redefines it, so a blueprint payload
    and an archived run-4 payload merge over the same defaults.
    """
    return dict(DEFAULT_FIELDS)


def z_to_mh(z: float) -> float:
    """[M/H] of a metal mass fraction Z under the form's own conventions."""
    y0, dy = _ENRICHMENT
    y = y0 + dy * z
    x = 1.0 - y - z
    return math.log10(z / x) - math.log10(_ZX_SUN)


def _on_grid(value: float) -> bool:
    return abs(value / MH_STEP - round(value / MH_STEP)) < 1e-9


def mh_grid(low: float, high: float) -> tuple[float, ...]:
    """The composition grid of a window: 0.1 dex steps plus exact edges.

    Steps land on multiples of 0.1 dex; a window edge that is not such a
    multiple is appended at its exact (stated or Z-converted) value, so
    both boundaries of every valid window are always part of the grid.
    """
    kmin = math.ceil(low / MH_STEP - 1e-9)
    kmax = math.floor(high / MH_STEP + 1e-9)
    values = [round(k * MH_STEP, 10) for k in range(kmin, kmax + 1)]
    for edge in (low, high):
        if not any(abs(v - edge) < 1e-9 for v in values):
            values.append(round(edge, 4))
    return tuple(sorted(values))


def _format(value: float) -> str:
    """A magnitude as its shortest exact decimal (0.34, -1.4921, 0.0)."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0.0" if text in ("", "0") else text


def mh_label(mh: float) -> str:
    """Directory label of a composition, run-4 compatible.

    Grid values render exactly as the existing product directories do
    (``mh_p0.0``, ``mh_m2.2``); boundary supplements keep their stated
    or converted precision (``mh_m2.19``, ``mh_m1.4921``).
    """
    return f"mh_{'m' if mh < 0 else 'p'}{_format(abs(mh))}"


def _mh_text(mh: float) -> str:
    """The [M/H] value as the form receives it (single-value job)."""
    return ("-" if mh < 0 else "") + _format(abs(mh))


@dataclass(frozen=True)
class TrackSet:
    """One (track_parsec, track_colibri) pair the form accepts.

    ``mh_low``/``mh_high`` are the effective [M/H] window: the form's own
    stated [M/H] range for the PARSEC set, narrowed by a COLIBRI option's
    Z range only when its enrichment-law conversion falls strictly inside
    that stated range (``mh_window`` records which).
    """

    key: str
    tier: str
    track_parsec: str
    track_colibri: str
    photsys_version: str
    photsys_file: str
    mh_low: float
    mh_high: float
    mh_window: str
    verify_header: str | None
    label_prefix: str = ""
    rotates: bool = False

    @property
    def mh_values(self) -> tuple[float, ...]:
        return mh_grid(self.mh_low, self.mh_high)

    @property
    def sparse_mh_values(self) -> tuple[float, ...]:
        """The secondary-tier initial slice of the same designed grid."""
        anchors = [v for v in SPARSE_ANCHOR_MH if self.mh_low - 1e-9 <= v <= self.mh_high + 1e-9]
        return tuple(sorted({*anchors, self.mh_low, self.mh_high}))

    @property
    def omega_values(self) -> tuple[float, ...]:
        return OMEGA_VALUES if self.rotates else (0.0,)


_TRACK_FIELDS = {
    "v1.2S": "parsec_CAF09_v1.2S",
    "v2.0": "parsec_CAF09_v2.0",
    "v1.1": "parsec_CAF09_v1.1",
    "v1.0": "parsec_CAF09_v1.0",
}
_YBC = {
    "photsys_version": "YBCnewVega",
    "photsys_file": "YBC_tab_mag_odfnew/tab_mag_ubvrijhk.dat",
}
_OBC = {
    "photsys_version": "odfnew",
    "photsys_file": "tab_mag_odfnew/tab_mag_lsst.dat",
}

#: S35/S07 accept 0.0005 <= Z <= 0.03 (stated in Z only); converted through
#: the enrichment law these are the window edges used below.
_S35_LOW = round(z_to_mh(0.0005), 4)
_S35_HIGH = round(z_to_mh(0.03), 4)

#: The eight designed sets. Windows: stated-in-[M/H] ranges are the form's
#: own acceptance numbers (verified end to end by the run-4 fetch); the
#: NOV13 option's Z range (0.0001-0.06) converts to [-2.1917, +0.6953],
#: which does NOT narrow the stated v1.2S window — an upstream
#: inconsistency resolved in favor of the stated window that the server
#: demonstrably serves.
TRACK_SETS: dict[str, TrackSet] = {
    s.key: s
    for s in (
        TrackSet(
            key="v1.2S_COLIBRI_web",
            tier="primary",
            track_parsec=_TRACK_FIELDS["v1.2S"],
            track_colibri="parsec_CAF09_v1.2S_S_LMC_08_web",
            photsys_version=_YBC["photsys_version"],
            photsys_file=_YBC["photsys_file"],
            mh_low=-2.2,
            mh_high=0.5,
            mh_window="stated for v1.2S: -2.2 to +0.5",
            verify_header="PARSEC release v1.2S +  COLIBRI S_37 + S_35 + PR16",
        ),
        TrackSet(
            key="v2.0",
            tier="primary",
            track_parsec=_TRACK_FIELDS["v2.0"],
            track_colibri="no",
            photsys_version=_YBC["photsys_version"],
            photsys_file=_YBC["photsys_file"],
            mh_low=-2.19,
            mh_high=0.34,
            mh_window="stated for v2.0: -2.19 to +0.34",
            verify_header="PARSEC release v2.0",
            rotates=True,
        ),
        TrackSet(
            key="v1.2S_COLIBRI_S35",
            tier="secondary",
            track_parsec=_TRACK_FIELDS["v1.2S"],
            track_colibri="parsec_CAF09_v1.2S_S35",
            photsys_version=_OBC["photsys_version"],
            photsys_file=_OBC["photsys_file"],
            mh_low=_S35_LOW,
            mh_high=_S35_HIGH,
            mh_window=(
                "COLIBRI S35 Z range 0.0005-0.03 converted via the "
                "enrichment law (narrower than the stated v1.2S window)"
            ),
            verify_header="PARSEC release v1.2S +  COLIBRI S_35",
        ),
        TrackSet(
            key="v1.2S_COLIBRI_S07",
            tier="secondary",
            track_parsec=_TRACK_FIELDS["v1.2S"],
            track_colibri="parsec_CAF09_v1.2S_S07",
            photsys_version=_OBC["photsys_version"],
            photsys_file=_OBC["photsys_file"],
            mh_low=_S35_LOW,
            mh_high=_S35_HIGH,
            mh_window=(
                "COLIBRI S07 Z range 0.0005-0.03 converted via the "
                "enrichment law (narrower than the stated v1.2S window)"
            ),
            verify_header="PARSEC release v1.2S +  COLIBRI S_07",
        ),
        TrackSet(
            key="v1.2S_COLIBRI_PR16",
            tier="secondary",
            track_parsec=_TRACK_FIELDS["v1.2S"],
            track_colibri="parsec_CAF09_v1.2S_NOV13",
            photsys_version=_OBC["photsys_version"],
            photsys_file=_OBC["photsys_file"],
            mh_low=-2.2,
            mh_high=0.5,
            mh_window=(
                "stated for v1.2S: -2.2 to +0.5 (NOV13's Z range "
                "0.0001-0.06 does not narrow it)"
            ),
            verify_header="PARSEC release v1.2S + COLIBRI release PR16",
        ),
        TrackSet(
            key="v1.2S_no_colibri",
            tier="secondary",
            track_parsec=_TRACK_FIELDS["v1.2S"],
            track_colibri="no",
            photsys_version=_OBC["photsys_version"],
            photsys_file=_OBC["photsys_file"],
            mh_low=-2.2,
            mh_high=0.5,
            mh_window="stated for v1.2S: -2.2 to +0.5 (no COLIBRI: no Z limit)",
            verify_header="PARSEC release v1.2S",
        ),
        TrackSet(
            key="v1.1",
            tier="secondary",
            track_parsec=_TRACK_FIELDS["v1.1"],
            track_colibri="no",
            photsys_version=_OBC["photsys_version"],
            photsys_file=_OBC["photsys_file"],
            mh_low=-2.2,
            mh_high=0.5,
            mh_window="stated for v1.1: -2.2 to +0.5",
            verify_header=None,
            label_prefix="v1.1_",
        ),
        TrackSet(
            key="v1.0",
            tier="secondary",
            track_parsec=_TRACK_FIELDS["v1.0"],
            track_colibri="no",
            photsys_version=_OBC["photsys_version"],
            photsys_file=_OBC["photsys_file"],
            mh_low=-1.5,
            mh_high=0.6,
            mh_window="stated for v1.0: -1.5 to +0.6",
            verify_header=None,
            label_prefix="v1.0_",
        ),
    )
}


def expected_log_ages() -> int:
    """Isochrone count the log grid designs (6.6 to <=10.13 by 0.02)."""
    low, upp, step = (float(v) for v in LOG_AGE_GRID)
    return math.floor((upp - low) / step + 1e-9) + 1


def expected_linear_ages() -> int:
    """Isochrone count the linear grid designs (0 to 4.0e6 yr by 1e5)."""
    low, upp, step = (float(v) for v in LINEAR_AGE_GRID)
    return math.floor((upp - low) / step + 1e-9) + 1


@dataclass(frozen=True)
class Cell:
    """One blueprint cell: a directory the finished database will hold.

    A cell is one (track set, [M/H], omega_i) point carrying BOTH age
    grids as separate archived submissions in the same directory: the
    log-age table as ``output.dat`` (the name the existing products
    already use) and the linear-age refinement as ``output_linear.dat``,
    each with its own acquisition record.
    """

    set: TrackSet
    mh: float
    omega: float

    @property
    def label(self) -> str:
        base = mh_label(self.mh)
        suffix = "" if self.omega == 0.0 else f"_w{self.omega:.2f}"
        return f"{self.set.label_prefix}{base}{suffix}"

    @property
    def relative_dir(self) -> str:
        return f"{self.set.key}/{self.label}"

    def _track_fields(self) -> dict[str, str]:
        return {
            "track_parsec": self.set.track_parsec,
            "track_colibri": self.set.track_colibri,
            "track_omegai": f"{self.omega:.2f}",
            "photsys_version": self.set.photsys_version,
            "photsys_file": self.set.photsys_file,
            "isoc_ismetlog": "1",
            "isoc_metlow": _mh_text(self.mh),
            "isoc_metupp": _mh_text(self.mh),
            "isoc_dmet": "0",
        }

    def log_fields(self) -> dict[str, str]:
        """Payload overrides of the log-age submission (output.dat)."""
        return {
            **self._track_fields(),
            "isoc_isagelog": "1",
            "isoc_lagelow": LOG_AGE_GRID[0],
            "isoc_lageupp": LOG_AGE_GRID[1],
            "isoc_dlage": LOG_AGE_GRID[2],
        }

    def linear_fields(self) -> dict[str, str]:
        """Payload overrides of the linear-age submission (output_linear.dat)."""
        return {
            **self._track_fields(),
            "isoc_isagelog": "0",
            "isoc_agelow": LINEAR_AGE_GRID[0],
            "isoc_ageupp": LINEAR_AGE_GRID[1],
            "isoc_dage": LINEAR_AGE_GRID[2],
        }


def cells(track_set: TrackSet | str, *, sparse: bool = False) -> tuple[Cell, ...]:
    """The designed cells of one set; ``sparse`` selects the secondary
    tier's initial slice instead of the full extent."""
    ts = TRACK_SETS[track_set] if isinstance(track_set, str) else track_set
    if sparse and ts.tier != "secondary":
        raise ValueError(
            f"set {ts.key!r} is {ts.tier!r}; sparse slices exist only for "
            "secondary sets"
        )
    mh_values = ts.sparse_mh_values if sparse else ts.mh_values
    return tuple(
        Cell(set=ts, mh=mh, omega=w) for mh in mh_values for w in ts.omega_values
    )


def all_cells() -> Iterator[Cell]:
    """Every designed cell of the full blueprint, all sets, full extent."""
    for ts in TRACK_SETS.values():
        yield from cells(ts)
