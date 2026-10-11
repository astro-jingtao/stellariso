"""Local isochrone synthesis from stellar tracks.

PARSEC publishes stellar tracks as official packages but no isochrone
packages (its CMD web form computes isochrone tables server-side on
request — opaque, and rejected as an acquisition channel); this module
builds isochrones locally and transparently instead: for a target age,
each track's time series is interpolated linearly in age between its
bracketing models, and the resulting points (one per initial mass) form
the isochrone. No cross-track interpolation, no extrapolation: a track
whose age span does not cover the target is omitted and the omission is
recorded. The helium-flash discontinuity is not bridged — HB tracks are
excluded from synthesis, so post-flash populations are absent from
synthesized isochrones at old ages (recorded, not hidden).

Every synthesized isochrone carries the transformation statement in its
provenance and the identity product ``synthesized_isochrones``; reading one
emits :class:`stellariso.warnings.SynthesizedProductWarning`.
"""

from __future__ import annotations

import dataclasses
import math
import warnings
from typing import TYPE_CHECKING, Iterable, Sequence

import numpy as np
from astropy.table import Table, vstack

from stellariso.core import (
    FieldOrigin,
    FieldSpec,
    ModelIdentity,
    ParameterRole,
    ParameterSource,
    ParameterSpec,
)
from stellariso.exceptions import DataIntegrityError
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.native import NativeTable
from stellariso.provenance import Provenance, Reference
from stellariso.registry import references
from stellariso.warnings import PhaseMappingWarning, SynthesizedProductWarning

if TYPE_CHECKING:  # pragma: no cover - typing only
    from stellariso.models.parsec.tracks import ParsecTrack, ParsecTrackSet

__all__ = ["SynthesisRecord", "synthesize_isochrone", "synthesize_isochrones"]

# IAU 2015 nominal solar mass parameter; CODATA 2018 G (cgs)
_M_SUN_G = 1.98847e33
_G_CGS = 6.67430e-8

# native track columns carried into the synthesized isochrone
_CARRIED = (
    "MASS",
    "LOG_L",
    "LOG_TE",
    "LOG_R",
    "M_CORE_HE",
    "M_CORE_C",
    "PHASE",
)
_UNIFIED_NAME = {
    "MASS": "current_mass",
    "LOG_L": "log_luminosity",
    "LOG_TE": "log_effective_temperature",
    "LOG_R": "log_radius_native_cm",  # shifted after interpolation
    "M_CORE_HE": "he_core_mass",
    "M_CORE_C": "co_core_mass",
    "PHASE": "native_phase",
}


class SynthesisRecord:
    """What one synthesis did: ages, tracks used and omitted, method."""

    def __init__(
        self,
        log_age: float,
        used: tuple[float, ...],
        omitted: tuple[tuple[float, str], ...],
        method: str,
    ):
        self.log_age = log_age
        self.used = used
        self.omitted = omitted
        self.method = method

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return (
            f"SynthesisRecord(log_age={self.log_age}, used={len(self.used)} "
            f"tracks, omitted={len(self.omitted)})"
        )


def _interpolate_track(track: ParsecTrack, log_age: float) -> dict[str, float] | None:
    """One track's state at ``log_age``, or None with the reason logged by
    the caller through the bracket check."""
    ages = np.asarray(track.native["AGE"], dtype=float)
    target = 10.0**log_age
    if target < ages[0] or target > ages[-1]:
        return None
    out: dict[str, float] = {}
    for col in _CARRIED:
        out[_UNIFIED_NAME[col]] = float(
            np.interp(target, ages, np.asarray(track.native[col], dtype=float))
        )
    return out


def _stage_of(track, log_age: float) -> str:
    """Unified stage from the interpolated PHASE code (floored), with the
    bracketing rule: if the bracketing models' codes floor to different
    stages, the point straddles a boundary and is reported as unknown."""
    ages = np.asarray(track.native["AGE"], dtype=float)
    target = 10.0**log_age
    phase = np.asarray(track.native["PHASE"], dtype=float)
    i = int(np.searchsorted(ages, target, side="right")) - 1
    i = min(max(i, 0), len(ages) - 1)
    bracket = [phase[j] for j in (i, min(i + 1, len(ages) - 1))]
    codes = [int(math.floor(p + 1e-9)) for p in bracket]
    if codes[0] != codes[1]:
        warnings.warn(
            f"mass {track.initial_mass} at log_age {log_age} straddles a "
            f"phase-code boundary ({codes[0]} / {codes[1]}); stage set to "
            "'unknown'",
            PhaseMappingWarning,
            stacklevel=3,
        )
        return "unknown"
    stages = track.computations["phase"](track.native)
    # stages is a full-column computation; index by the bracketing node
    return str(stages[i])


def _synthesized_specs(base: dict[str, FieldSpec], present: Sequence[str]) -> dict[str, FieldSpec]:
    specs = {}
    for name in present:
        source = base.get(name)
        if source is None:
            continue
        specs[name] = dataclasses.replace(
            source,
            origin=FieldOrigin.NATIVE,
            native_name=name,
            native_unit=source.unit,
            transformation=None,
            description=(
                f"synthesized at isochrone construction by {source.backend} "
                "track interpolation (see the provenance transformation); "
                + (source.description or "")
            ).strip(),
        )
    return specs


def synthesize_isochrone(
    tracks: "ParsecTrackSet | Iterable[ParsecTrack]",
    log_age: float,
    method: str = "linear",
) -> Isochrone:
    """Synthesize one isochrone at ``log_age`` from PARSEC v1.2S tracks."""
    if method != "linear":
        raise ValueError(
            "synthesis supports method='linear' (within-track interpolation "
            f"in age); got {method!r}"
        )
    from stellariso.models.parsec.tracks import ParsecTrackSet

    if isinstance(tracks, ParsecTrackSet):
        standard = tracks.tracks
        hb = tracks.hb_tracks
        track_set = tracks
    else:
        standard = [t for t in tracks if t.kind == "standard"]
        hb = [t for t in tracks if t.kind == "hb"]
        track_set = None

    rows = []
    used, omitted = [], []
    for track in sorted(standard, key=lambda t: t.initial_mass):
        state = _interpolate_track(track, log_age)
        if state is None:
            ages = np.asarray(track.native["AGE"], dtype=float)
            reason = (
                "age before track start"
                if 10.0**log_age < ages[0]
                else "age beyond track end (He flash / track termination)"
            )
            omitted.append((track.initial_mass, reason))
            continue
        stage = _stage_of(track, log_age)
        log_r_cm = state["log_radius_native_cm"]
        radius_log_rsun = log_r_cm - math.log10(6.957e10)
        log_g = math.log10(
            _G_CGS * state["current_mass"] * _M_SUN_G / (10.0**log_r_cm) ** 2
        )
        rows.append(
            {
                "initial_mass": track.initial_mass,
                "current_mass": state["current_mass"],
                "log_luminosity": state["log_luminosity"],
                "log_effective_temperature": state["log_effective_temperature"],
                "log_radius": radius_log_rsun,
                "log_surface_gravity": log_g,
                "he_core_mass": state["he_core_mass"],
                "co_core_mass": state["co_core_mass"],
                "native_phase": state["native_phase"],
                "phase": stage,
            }
        )
        used.append(track.initial_mass)
    if hb:
        omitted.extend((t.initial_mass, "hb track excluded from synthesis") for t in hb)
    if not rows:
        raise DataIntegrityError(
            f"no track covers log_age={log_age}; "
            f"omissions: {omitted[:10]}"
        )

    rows.sort(key=lambda r: r["initial_mass"])
    columns = {name: [row[name] for row in rows] for name in rows[0]}
    table = Table(columns)
    native = NativeTable(
        table=table,
        header=(),
        metadata={
            "stellariso_layer": "synthesized",
            "log_age": log_age,
            "n_tracks_used": len(used),
            "omitted": [list(o) for o in omitted],
        },
    )

    from stellariso.models.parsec.tracks import _FIELD_SPECS as track_specs

    specs = _synthesized_specs(track_specs, list(rows[0]))
    identity = ModelIdentity(
        family="parsec",
        release="v1.2S",
        product="synthesized_isochrones",
        physics_configuration=(
            f"Z{track_set.initial_z}Y{track_set.initial_helium}"
            if track_set is not None
            and track_set.initial_z is not None
            and track_set.initial_helium is not None
            else None
        ),
        description=(
            "isochrone synthesized locally by stellariso from PARSEC v1.2S "
            "stellar tracks (linear interpolation in age within each "
            "track); NOT a model-team isochrone product"
        ),
    )
    z = track_set.initial_z if track_set is not None else None
    y = track_set.initial_helium if track_set is not None else None
    parameters = (
        ParameterSpec(
            name="log_age",
            role=ParameterRole.AXIS,
            values=(log_age,),
            unit="dex(log10(age/yr))",
            source=ParameterSource.DERIVED_BY_STELLARISO,
            description="the synthesis target age",
        ),
        ParameterSpec(
            name="initial_mass",
            role=ParameterRole.AXIS,
            values=tuple(r["initial_mass"] for r in rows),
            unit="solMass",
            source=ParameterSource.NATIVE,
            description="initial masses of the tracks used",
        ),
    )
    if z is not None:
        parameters += (
            ParameterSpec(
                name="initial_z", role=ParameterRole.FIXED, value=z,
                source=ParameterSource.NATIVE,
            ),
        )
    if y is not None:
        parameters += (
            ParameterSpec(
                name="initial_helium", role=ParameterRole.FIXED, value=y,
                source=ParameterSource.NATIVE,
            ),
        )

    base_prov = track_set.provenance if track_set is not None else Provenance()
    n_hb = len(hb)
    transformation = (
        f"isochrone at log_age={log_age:g} synthesized from {len(used)} "
        "PARSEC v1.2S tracks by linear interpolation in age within each "
        f"track ({len(omitted)} tracks omitted: age out of span or HB"
        + (f", {n_hb} of them HB" if n_hb else "")
        + "); no cross-track interpolation, no extrapolation"
    )
    provenance = Provenance(
        data_sources=base_prov.data_sources,
        assets=base_prov.assets,
        source_chains=base_prov.source_chains,
        scientific_references=base_prov.scientific_references or references("parsec"),
        software_references=(
            base_prov.software_references
            + (
                Reference(
                    citation="stellariso.synthesis (local isochrone "
                    "construction from PARSEC v1.2S tracks)"
                ),
            )
        ),
        transformations=base_prov.transformations + (transformation,),
    )

    warnings.warn(
        "this isochrone was synthesized locally from PARSEC v1.2S tracks by "
        "stellariso, not produced by the model team's isochrone pipeline; "
        f"provenance records the exact transformation. {len(omitted)} track(s) "
        "omitted (age out of span or HB).",
        SynthesizedProductWarning,
        stacklevel=2,
    )

    from stellariso.unified import UnifiedView

    selection = {"log_age": log_age}
    if z is not None:
        selection["initial_z"] = z
    return Isochrone(
        native=native,
        identity=identity,
        parameters=parameters,
        field_specs=specs,
        provenance=provenance,
        selection=selection,
        unified_view=UnifiedView(native, specs),
    )


def synthesize_isochrones(
    track_set: "ParsecTrackSet", log_ages: Iterable[float]
) -> IsochroneSet:
    """Synthesize one isochrone per age; returns a queryable IsochroneSet."""
    isochrones = tuple(synthesize_isochrone(track_set, a) for a in log_ages)
    if not isochrones:
        raise ValueError("log_ages must contain at least one value")
    stacked = vstack([iso.native.to_table() for iso in isochrones])
    native = NativeTable(
        table=stacked,
        header=(),
        metadata={"stellariso_layer": "synthesized", "n_isochrones": len(isochrones)},
    )
    return IsochroneSet(
        isochrones=isochrones,
        native=native,
        identity=isochrones[0].identity,
        parameters=isochrones[0].parameters,
        provenance=isochrones[0].provenance,
        indexer="log_age",
    )
