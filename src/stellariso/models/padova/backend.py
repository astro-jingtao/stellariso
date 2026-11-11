"""Padova backend: identity, parameters, computations, IsochroneSets.

The two legacy releases share this backend; everything release-specific
lives in the unified-parameter registry's two products and in the
reader's two layouts:

- padova/2000: every unified field except ``phase`` is a direct native
  column (Mini, Mact, logL, logTeff, logg); ``phase`` is anchored on the
  source's own isochsum.dat characteristic points.
- padova/1994: only log(Teff) is native; initial_mass (FLUM inversion),
  current_mass (M/Mwind branch), log_luminosity (Mbol zero point),
  log_surface_gravity (closure), and ``phase`` (shape rules) are all
  declared derived computations with their constants stated in the
  registry entry.
"""

from __future__ import annotations

import math
import os
import warnings
from pathlib import Path
from typing import TextIO

import numpy as np

from stellariso.core import ModelIdentity
from stellariso.exceptions import DataIntegrityError, SourceUnavailableError
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.native import NativeTable
from stellariso.provenance import Provenance
from stellariso.registry import field_spec_dict, references, resolve_parameters
from stellariso.unified import UnifiedView
from stellariso.warnings import PhaseMappingWarning
from stellariso.models.padova.reader import (
    SALPETER_ALPHA,
    STAGE_ANCHOR_ALIASES,
    parse_padova1994,
    parse_padova2000,
    parse_padova2000_summary,
    read_data_lines,
    recognize_padova,
    sniff_layout,
)

__all__ = [
    "read_padova",
    "recognize_padova",
    "padova_identity",
    "PADOVA_REFERENCES",
    "Z_REFERENCE_2000",
    "Z_REFERENCE_1994",
    "MBOL_SUN_1994",
    "invert_flum",
]

PADOVA_REFERENCES = references("padova")

#: solar Z each release's [Fe/H] conversion is anchored on (registry data)
Z_REFERENCE_2000 = 0.019
Z_REFERENCE_1994 = 0.02

#: declared bolometric-magnitude zero point of the 1994 logL derivation
MBOL_SUN_1994 = 4.77

_LOG_G_SUN = 4.438  # log10(cm/s2)
_LOG_TEFF_SUN = math.log10(5777.0)

#: Y per published Z of the 2000 grid (catalog ReadMe description text)
_Y_OF_Z_2000 = {
    0.0004: 0.23,
    0.001: 0.23,
    0.004: 0.24,
    0.008: 0.25,
    0.019: 0.273,
    0.03: 0.30,
}

_FIELD_SPECS = {
    "2000": field_spec_dict("padova", "isochrones_2000"),
    "1994": field_spec_dict("padova", "isochrones_1994"),
}

_STAGE_OF_BOUNDARY = (
    "subgiant",
    "red_giant_branch",
    "core_helium_burning",
    "early_asymptotic_giant_branch",
    "thermally_pulsing_asymptotic_giant_branch",
)


# -- identity and parameters -----------------------------------------------------


def padova_identity(release: str) -> ModelIdentity:
    if release == "2000":
        description = (
            "Girardi et al. 2000 theoretical isochrones (VizieR "
            "J/A+AS/141/371): ZAMS to TP-AGB or carbon ignition, 0.15 to "
            "7 Msun, overshooting grid plus a Schwarzschild-criterion "
            "solar comparison set"
        )
    else:
        description = (
            "Bertelli et al. 1994 theoretical isochrones (VizieR "
            "J/A+AS/106/275): ZAMS through the post-AGB/white-dwarf "
            "stage, 0.6 to 120 Msun, one (Z, Y) per table"
        )
    return ModelIdentity(
        family="padova",
        release=release,
        product="theoretical_isochrones",
        description=description,
    )


def _feh(z: float, z_reference: float) -> float:
    return math.log10(z / z_reference)


# -- padova/2000 phase: isochsum characteristic-point anchors ---------------------


def _stage_boundaries(anchors: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """Anchor masses and their stage labels, in mass order.

    A boundary whose anchor label is absent extends the previous stage
    (the chain just skips it). Boundary masses must be non-decreasing;
    a violation means the summary rows do not describe this isochrone
    in mass order and is a data error, not a mapping choice.
    """
    masses: list[float] = []
    stages: list[str] = []
    for aliases, stage in zip(STAGE_ANCHOR_ALIASES, _STAGE_OF_BOUNDARY):
        for label in aliases:
            if label in anchors:
                masses.append(anchors[label])
                stages.append(stage)
                break
    if masses and np.any(np.diff(masses) < -1e-9):
        found = {label: anchors.get(label) for aliases in STAGE_ANCHOR_ALIASES for label in aliases if label in anchors}
        raise DataIntegrityError(
            "isochsum characteristic points are not in initial-mass order: "
            f"{found}"
        )
    return np.asarray(masses), stages


def _phase_computation_2000(anchors: dict[str, float]):
    masses, stages = _stage_boundaries(anchors)
    labels = np.array(["main_sequence"] + stages, dtype=object)

    def compute(nt: NativeTable) -> np.ndarray:
        mini = np.asarray(nt["Mini"], dtype=float)
        idx = np.searchsorted(masses, mini, side="right")
        return labels[idx]

    return compute


def _phase_unavailable(reason: str):
    def compute(nt: NativeTable) -> np.ndarray:
        raise SourceUnavailableError(
            "the derived phase field of padova/2000 requires the source's "
            f"isochsum.dat characteristic points; {reason}"
        )

    return compute


def _load_summary(source) -> dict | None:
    """The isochsum anchors next to ``source``, or None when absent."""
    if hasattr(source, "read"):
        path_name = getattr(source, "name", None)
    else:
        path_name = str(source)
    if path_name is None:
        return None
    directory = Path(path_name).parent
    for name in ("isochsum.dat", "isochsum.dat.gz"):
        candidate = directory / name
        if candidate.exists():
            return parse_padova2000_summary(candidate)
    return None


# -- padova/1994 computations ------------------------------------------------------


def invert_flum(flum: np.ndarray) -> np.ndarray:
    """Mini from the tabulated Salpeter integral FLUM = Mini^(1-a)/(1-a)."""
    return ((SALPETER_ALPHA - 1.0) * np.abs(flum)) ** (1.0 / (1.0 - SALPETER_ALPHA))


def _p94_initial_mass(nt: NativeTable) -> np.ndarray:
    return invert_flum(np.asarray(nt["FLUM"], dtype=float))


def _p94_current_mass(nt: NativeTable) -> np.ndarray:
    m = np.asarray(nt["M"], dtype=float)
    mwind = np.asarray(nt["Mwind"], dtype=float)
    return np.where(mwind > 0, mwind, m)


def _p94_log_luminosity(nt: NativeTable) -> np.ndarray:
    return (MBOL_SUN_1994 - np.asarray(nt["Mbol"], dtype=float)) / 2.5


def _p94_log_surface_gravity(nt: NativeTable) -> np.ndarray:
    log_teff = np.asarray(nt["log(Teff)"], dtype=float)
    log_l = _p94_log_luminosity(nt)
    mass = _p94_current_mass(nt)
    return np.log10(mass) + 4.0 * (log_teff - _LOG_TEFF_SUN) - log_l + _LOG_G_SUN


# Shape-rule constants of the 1994 phase classification (see the registry
# entry's transformation text for what each one separates).
_MASS_DROP = 1e-3  # Msun; a current-mass discontinuity of the tables
_RGB_DROP_LOGF_DEX = 0.3  # RGB->HB drops break the luminosity; AGB->P-AGB do not
_TIP_DIP_DEX = 0.15  # luminosity fall that identifies the RGB-tip turning point
_TO_FALL_DEX = 0.1  # Teff fall off the main sequence that identifies the turnoff
_WR_MINI = 10.0  # Msun; stripped cores below this are not Wolf-Rayet stars


def _p94_phase(nt: NativeTable) -> np.ndarray:
    log_teff = np.asarray(nt["log(Teff)"], dtype=float)
    log_l = _p94_log_luminosity(nt)
    mass = np.asarray(nt["M"], dtype=float)
    mini = _p94_initial_mass(nt)
    n = len(log_teff)

    # 1. locate the current-mass discontinuities and classify each: an
    # RGB-to-HB jump breaks the luminosity (the ZAHB sits well below the
    # tip); the AGB-to-post-AGB jump does not (the luminosity carries
    # through at the tip level before the white-dwarf decline)
    drop_rows = np.flatnonzero(np.diff(mass) < -_MASS_DROP) + 1
    rgb_drop = None
    pagb_drop = None
    for i in drop_rows:
        pre = float(np.max(log_l[max(0, i - 3) : i]))
        post = float(np.min(log_l[i : i + 3])) if i < n else log_l[-1]
        if pre - post > _RGB_DROP_LOGF_DEX:
            if rgb_drop is None:
                rgb_drop = int(i)
        elif pagb_drop is None:
            pagb_drop = int(i)
    first_drop = n if len(drop_rows) == 0 else int(drop_rows[0])

    # 2. main-sequence turnoff: the first temperature maximum followed
    # by a >= _TO_FALL_DEX fall (the descent toward the giants). The
    # global maximum would misfire on the youngest isochrones, whose
    # stripped Wolf-Rayet tail is hotter than any main-sequence star.
    to, peak_v = 0, float(log_teff[0])
    for i in range(1, first_drop):
        if log_teff[i] > peak_v:
            peak_v, to = float(log_teff[i]), i
        elif peak_v - log_teff[i] >= _TO_FALL_DEX:
            break
    else:
        to = int(np.argmax(log_teff[:first_drop]))

    # 3. RGB tip: first luminosity maximum after the turnoff that is
    # followed by a >= _TIP_DIP_DEX fall before the post-AGB drop (the
    # fall at the RGB-to-HB transition itself completes it)
    limit = pagb_drop if pagb_drop is not None else n
    tip = None
    peak_i, peak_v = None, None
    for i in range(to + 1, limit):
        if peak_v is None or log_l[i] > peak_v:
            peak_v, peak_i = float(log_l[i]), i
        if peak_v - log_l[i] >= _TIP_DIP_DEX:
            tip = peak_i
            break
    if tip is None:
        tip = peak_i  # no completed fall: the running peak is the boundary

    # 4. He-burning ends where the luminosity re-exceeds the tip value
    cheb_end = None
    if tip is not None:
        for i in range(tip + 1, pagb_drop if pagb_drop is not None else n):
            if log_l[i] > log_l[tip] + 1e-9:
                cheb_end = i
                break

    # 5. the post-AGB/WD boundary: hottest point of the tail
    wd_start = None
    if pagb_drop is not None:
        wd_start = int(np.argmax(log_teff[pagb_drop:])) + pagb_drop

    stages = np.full(n, "main_sequence", dtype=object)
    stages[to + 1 :] = "red_giant_branch"
    if tip is not None and tip + 1 < n and tip > to:
        stages[tip + 1 :] = "core_helium_burning"
    if cheb_end is not None:
        stages[cheb_end:] = "early_asymptotic_giant_branch"
    if pagb_drop is not None:
        stages[pagb_drop:] = "post_agb"
    if wd_start is not None and wd_start + 1 < n:
        stages[wd_start + 1 :] = "white_dwarf"
    # stripped hot massive stars: hotter than the turnoff and massive —
    # nothing else in the isochrone can be (blue HB stars stay below
    # _WR_MINI initial mass)
    wr = (log_teff > log_teff[to]) & (mini > _WR_MINI)
    if wr.any():
        stages[wr] = "wolf_rayet"

    if tip is None or tip <= to or (cheb_end is not None and cheb_end <= tip):
        warnings.warn(
            "padova/1994 shape rules did not resolve a consistent stage "
            "chain for one isochrone (turnoff, RGB tip, or post-AGB "
            "boundary fell on a degenerate point); its rows are "
            "classified 'unknown'",
            PhaseMappingWarning,
            stacklevel=2,
        )
        stages[:] = "unknown"
    return stages


_P94_COMPUTATIONS = {
    "initial_mass": _p94_initial_mass,
    "current_mass": _p94_current_mass,
    "log_luminosity": _p94_log_luminosity,
    "log_surface_gravity": _p94_log_surface_gravity,
    "phase": _p94_phase,
}


# -- reading -----------------------------------------------------------------------


def _attach_references(provenance: Provenance | None) -> Provenance:
    prov = provenance if provenance is not None else Provenance()
    if not prov.scientific_references:
        prov = Provenance(
            data_sources=prov.data_sources,
            assets=prov.assets,
            source_chains=prov.source_chains,
            scientific_references=PADOVA_REFERENCES,
            software_references=prov.software_references,
            transformations=prov.transformations,
        )
    return prov


def _helium_2000(z: float) -> float:
    try:
        return _Y_OF_Z_2000[round(z, 5)]
    except KeyError:
        raise DataIntegrityError(
            f"Z = {z} is not one of the six published padova/2000 "
            f"compositions {sorted(_Y_OF_Z_2000)}; the ReadMe pairing table "
            "no longer describes this file"
        ) from None


def _read_2000(source, provenance: Provenance | None) -> IsochroneSet:
    parsed = parse_padova2000(source)
    summary = _load_summary(source)
    identity = padova_identity("2000")
    specs = _FIELD_SPECS["2000"]

    z_values = sorted({b.z for b in parsed.blocks})
    dynamic = {
        "log_age": tuple(sorted({b.log_age for b in parsed.blocks})),
        "initial_z": tuple(z_values),
        "initial_helium": tuple(sorted(_helium_2000(z) for z in z_values)),
        "overshoot": tuple(sorted({float(b.overshoot) for b in parsed.blocks})),
        "initial_feh": tuple(sorted(_feh(z, Z_REFERENCE_2000) for z in z_values)),
    }
    params = resolve_parameters("padova", "isochrones_2000", dynamic)
    prov = _attach_references(provenance)

    isochrones = []
    for block, meta in zip(parsed.blocks, parsed.native.block_metadata):
        # [Fe/H] is the composition selection coordinate (the consumer
        # contract's display system); Z stays in the parameters, the
        # block metadata, and the native Z column
        selection = {
            "log_age": block.log_age,
            "initial_feh": _feh(block.z, Z_REFERENCE_2000),
            "overshoot": float(block.overshoot),
        }
        block_native = NativeTable(
            table=parsed.native.table[block.row_start : block.row_stop],
            header=(),
            metadata=dict(parsed.native.metadata),
            block_metadata=(dict(meta),),
        )
        key = (block.overshoot, block.z, block.log_age)
        if summary is not None and key in summary:
            phase = _phase_computation_2000(summary[key])
        elif summary is not None:
            phase = _phase_unavailable(
                f"no characteristic points exist for grid point {key}"
            )
        else:
            phase = _phase_unavailable(
                "place isochsum.dat (or isochsum.dat.gz) next to isochron.dat"
            )

        isochrones.append(
            Isochrone(
                native=block_native,
                identity=identity,
                parameters=params,
                field_specs=specs,
                provenance=prov,
                selection=selection,
                unified_view=UnifiedView(
                    block_native, specs, computations={"phase": phase}
                ),
            )
        )
    return IsochroneSet(
        isochrones=tuple(isochrones),
        native=parsed.native,
        identity=identity,
        parameters=params,
        provenance=prov,
        indexer="log_age",
    )


def _read_1994(source, provenance: Provenance | None) -> IsochroneSet:
    parsed = parse_padova1994(source)
    z = parsed.facts["initial_z"]
    y = parsed.facts["initial_helium"]
    feh = _feh(z, Z_REFERENCE_1994)
    identity = padova_identity("1994")
    specs = _FIELD_SPECS["1994"]

    dynamic = {
        "log_age": tuple(sorted(b.log_age for b in parsed.blocks)),
        "initial_z": (z,),
        "initial_helium": (y,),
        "initial_feh": (feh,),
    }
    params = resolve_parameters("padova", "isochrones_1994", dynamic)
    prov = _attach_references(provenance)

    isochrones = []
    for block, meta in zip(parsed.blocks, parsed.native.block_metadata):
        selection = {"log_age": block.log_age, "initial_feh": feh}
        block_native = NativeTable(
            table=parsed.native.table[block.row_start : block.row_stop],
            header=(),
            metadata=dict(parsed.native.metadata),
            block_metadata=(dict(meta),),
        )
        isochrones.append(
            Isochrone(
                native=block_native,
                identity=identity,
                parameters=params,
                field_specs=specs,
                provenance=prov,
                selection=selection,
                unified_view=UnifiedView(
                    block_native, specs, computations=dict(_P94_COMPUTATIONS)
                ),
            )
        )
    return IsochroneSet(
        isochrones=tuple(isochrones),
        native=parsed.native,
        identity=identity,
        parameters=params,
        provenance=prov,
        indexer="log_age",
    )


def read_padova(
    source: str | os.PathLike | TextIO,
    provenance: Provenance | None = None,
) -> IsochroneSet:
    """Read one padova archive file into an IsochroneSet."""
    layout = sniff_layout(read_data_lines(source)[:1])
    if layout == "2000":
        return _read_2000(source, provenance)
    if layout == "1994":
        return _read_1994(source, provenance)
    raise SourceUnavailableError(
        "the source is neither padova layout (isochron.dat of "
        "J/A+AS/141/371, or a table1..table6 file of J/A+AS/106/275)"
    )
