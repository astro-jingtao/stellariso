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

from stellariso.core import ModelIdentity
from stellariso.exceptions import DataIntegrityError
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.native import NativeTable
from stellariso.provenance import Provenance
from stellariso.registry import (
    eep_anchors,
    field_spec_dict,
    phase_mapping,
    references,
    resolve_parameters,
)
from stellariso.unified import UnifiedView
from stellariso.models.mist.reader import MistFile, open_mist_text, parse_mist_iso

__all__ = [
    "read_mist",
    "recognize_mist",
    "mist_identity",
    "mist_parameters",
    "MIST_REFERENCES",
    "MIST_EEP_ANCHORS",
]

_FIELD_SPEC_DICT = field_spec_dict("mist", "isochrones")
_MIST_PHASE_MAPPING = phase_mapping("mist", "isochrones")
_PHASE_COMPUTATION = {"phase": lambda nt: _MIST_PHASE_MAPPING(np.asarray(nt["phase"]))}
MIST_REFERENCES = references("mist")
MIST_EEP_ANCHORS = eep_anchors("mist", "isochrones") or {}


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


def mist_parameters(facts: dict, log_ages: tuple) -> tuple:
    """ParameterSpecs for one MIST theoretical-isochrone file.

    Static knowledge (roles, conventions, implicit parameters, the
    published v1.2 rotation set) comes from the unified-parameter registry;
    the file header supplies the values only it knows (Yinit/Zinit, this
    file's [Fe/H] and [a/Fe], the age list from the blocks).
    """
    dynamic = {
        "log_age": tuple(sorted(set(log_ages))),
        "initial_feh": (facts["feh"],),
        "alpha_fe": (facts["afe"],),
        "initial_helium": facts["yinit"],
        "initial_z": facts["zinit"],
    }
    return resolve_parameters("mist", "isochrones", dynamic)


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
                    block_native,
                    _FIELD_SPEC_DICT,
                    computations=_PHASE_COMPUTATION,
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
