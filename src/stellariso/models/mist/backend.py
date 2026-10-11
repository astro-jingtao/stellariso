"""MIST backend: product knowledge around the raw parser.

Builds the :class:`ModelIdentity`, the :class:`ParameterSpec` tuple, and the
:class:`IsochroneSet` for a parsed MIST theoretical-isochrone file. All
values stated by the file header are taken from it; values stated only in
official documentation cite their source. Nothing is inferred silently.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO

import numpy as np

from stellariso.core import ModelIdentity, ParameterRole, ParameterSource, ParameterSpec
from stellariso.exceptions import DataIntegrityError
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.native import NativeTable
from stellariso.provenance import Provenance, Reference
from stellariso.unified import UnifiedView
from stellariso.models.mist.mappings import MIST_FIELD_SPECS, MIST_PHASE_MAPPING
from stellariso.models.mist.reader import MistFile, open_mist_text, parse_mist_iso

__all__ = [
    "read_mist",
    "recognize_mist",
    "mist_identity",
    "mist_parameters",
    "MIST_REFERENCES",
]

MAPPING_VERSION = "1"

_FIELD_SPEC_DICT = {spec.name: spec for spec in MIST_FIELD_SPECS}


def recognize_mist(source: str | os.PathLike | TextIO) -> bool:
    """Cheap sniff: does this source look like a MIST theoretical isochrone file?

    Reads only the first few comment lines; never parses the table body.
    """
    fh, opened = open_mist_text(source)
    try:
        seen_version = seen_block = False
        for _ in range(15):
            line = fh.readline()
            if not line:
                break
            if "MIST version number" in line:
                seen_version = True
            if "number of EEPs, cols" in line:
                seen_block = True
            if seen_version and seen_block:
                return True
        return False
    except (OSError, UnicodeDecodeError):
        return False
    finally:
        if opened:
            fh.close()

MIST_REFERENCES = (
    Reference(
        citation="Choi, J., Dotter, A., Conroy, C., et al. 2016, ApJ, 823, 102",
        bibcode="2016ApJ...823..102C",
        ads_url="https://ui.adsabs.harvard.edu/abs/2016ApJ...823..102C",
    ),
    Reference(
        citation="Dotter, A. 2016, ApJS, 222, 8",
        bibcode="2016ApJS..222....8D",
        ads_url="https://ui.adsabs.harvard.edu/abs/2016ApJS..222....8D",
    ),
    Reference(
        citation="Paxton, B., et al. 2011, ApJS, 192, 3 (MESA I)",
        bibcode="2011ApJS..192....3P",
    ),
)

# Rotation values published for the MIST v1.2 isochrone suite (separate
# tarballs per v/vcrit); the header of each file states which one it holds.
_V1P2_ROTATION_VALUES = (0.0, 0.4)


def mist_identity(facts: dict) -> ModelIdentity:
    version = str(facts.get("mist_version", "unknown"))
    vvcrit = facts.get("vvcrit")
    physics = f"vvcrit{vvcrit}" if vvcrit is not None else None
    return ModelIdentity(
        family="mist",
        release=version,
        product="theoretical_isochrones",
        version=f"MESA r{facts['mesa_revision']}" if "mesa_revision" in facts else None,
        physics_configuration=physics,
        description="MIST theoretical isochrones (no photometry), theory output",
    )


def mist_parameters(facts: dict, log_ages: tuple) -> tuple[ParameterSpec, ...]:
    """ParameterSpecs for one MIST theoretical-isochrone file.

    The published suite varies age, [Fe/H] (form-generated, effectively
    continuous; tarball suites use a fixed set), [a/Fe], and v/vcrit (two
    tarballs per release) — these are ``axis`` parameters whose value for
    this file is pinned in each isochrone's selection metadata. The file
    header's Yinit/Zinit are ``fixed`` for the file with ``native`` source.
    """
    feh = facts["feh"]
    afe = facts["afe"]
    vvcrit = facts["vvcrit"]
    return (
        ParameterSpec(
            name="log_age",
            role=ParameterRole.AXIS,
            values=tuple(sorted(set(log_ages))),
            unit="dex(log10(age/yr))",
            description="log10 of isochrone age in years",
            source=ParameterSource.NATIVE,
        ),
        ParameterSpec(
            name="initial_feh",
            role=ParameterRole.AXIS,
            values=(feh,),
            unit="dex",
            convention="[Fe/H] of the initial composition, MIST scale",
            description="initial metallicity as [Fe/H]",
            source=ParameterSource.NATIVE,
        ),
        ParameterSpec(
            name="alpha_fe",
            role=ParameterRole.AXIS,
            values=(afe,),
            unit="dex",
            convention="[a/Fe]",
            description="alpha enhancement of the initial composition",
            source=ParameterSource.NATIVE,
        ),
        ParameterSpec(
            name="initial_rotation",
            role=ParameterRole.AXIS,
            values=_V1P2_ROTATION_VALUES,
            unit=None,
            convention="v_initial / v_critical (surface equatorial)",
            description=(
                "initial rotation ratio; the MIST v1.2 suite publishes "
                "separate products for each value, this file pins one"
            ),
            source=ParameterSource.OFFICIAL_DOCUMENTATION,
        ),
        ParameterSpec(
            name="initial_helium",
            role=ParameterRole.FIXED,
            value=facts["yinit"],
            source=ParameterSource.NATIVE,
            description="initial helium mass fraction (MIST Y-Z grid point)",
        ),
        ParameterSpec(
            name="initial_z",
            role=ParameterRole.FIXED,
            value=facts["zinit"],
            source=ParameterSource.NATIVE,
            description="initial metal mass fraction (MIST Y-Z grid point)",
        ),
        ParameterSpec(
            name="mixing_length",
            role=ParameterRole.IMPLICIT,
            status="not_reported",
            description="MESA calibrates alpha_ML on the Sun; value not in data",
        ),
        ParameterSpec(
            name="overshoot",
            role=ParameterRole.IMPLICIT,
            status="not_reported",
        ),
        ParameterSpec(
            name="atomic_diffusion",
            role=ParameterRole.IMPLICIT,
            status="not_reported",
        ),
    )


def read_mist(
    source: str | os.PathLike | TextIO,
    provenance: Provenance | None = None,
) -> IsochroneSet:
    """Read one MIST ``.iso`` (or ``.iso.gz``) into an IsochroneSet."""
    parsed: MistFile = parse_mist_iso(source)
    native = parsed.native
    facts = parsed.facts
    identity = mist_identity(facts)

    # Per-file parameters: log_age axis values come from the blocks.
    log_ages = []
    for block in parsed.blocks:
        age_col = native.table["log10_isochrone_age_yr"][block.row_start : block.row_stop]
        unique = np.unique(np.round(age_col, decimals=8))
        if len(unique) != 1:
            raise DataIntegrityError(
                f"isochrone block declaring {block.n_eeps} EEPs spans "
                f"{len(unique)} distinct ages: {unique[:5]}"
            )
        log_ages.append(float(unique[0]))
    params = mist_parameters(facts, tuple(log_ages))

    prov = provenance if provenance is not None else Provenance()
    if not prov.scientific_references:
        prov = Provenance(
            data_sources=prov.data_sources,
            assets=prov.assets,
            source_chains=prov.source_chains,
            scientific_references=MIST_REFERENCES,
            software_references=prov.software_references,
            transformations=prov.transformations,
        )

    isochrones = []
    for block, log_age, block_meta in zip(parsed.blocks, log_ages, native.block_metadata):
        selection = {
            "log_age": log_age,
            "initial_feh": facts["feh"],
            "alpha_fe": facts["afe"],
            "initial_rotation": facts["vvcrit"],
        }
        block_native = NativeTable(
            table=native.table[block.row_start : block.row_stop],
            header=block.header_lines,
            metadata=dict(native.metadata),
            block_metadata=(dict(block_meta),),
        )
        isochrones.append(
            Isochrone(
                native=block_native,
                identity=identity,
                parameters=params,
                field_specs=_FIELD_SPEC_DICT,
                provenance=prov,
                selection=selection,
                unified_view=UnifiedView(
                    block_native, _FIELD_SPEC_DICT, MIST_PHASE_MAPPING
                ),
            )
        )

    return IsochroneSet(
        isochrones=tuple(isochrones),
        native=native,
        identity=identity,
        parameters=params,
        provenance=prov,
        indexer="log_age",
    )
