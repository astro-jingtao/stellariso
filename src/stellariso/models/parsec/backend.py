"""PARSEC backend: identity, parameters, IsochroneSet construction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO

import numpy as np

from stellariso.core import ModelIdentity
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.native import NativeTable
from stellariso.provenance import Provenance
from stellariso.registry import (
    field_spec_dict,
    phase_mapping,
    references,
    resolve_parameters,
)
from stellariso.unified import UnifiedView
from stellariso.models.parsec.reader import ParsecFile, parse_parsec_cmd

__all__ = ["read_parsec", "recognize_parsec", "PARSEC_REFERENCES"]

PARSEC_REFERENCES = references("parsec")
_FIELD_SPEC_DICT = field_spec_dict("parsec", "cmd_table")
_PARSEC_PHASE_MAPPING = phase_mapping("parsec", "cmd_table")
_PHASE_COMPUTATION = {
    "phase": lambda nt: _PARSEC_PHASE_MAPPING(np.asarray(nt["label"]))
}


def recognize_parsec(source: str | os.PathLike | TextIO) -> bool:
    """Cheap sniff for CMD isochrone tables (header + column signature)."""
    from stellariso.models.parsec.reader import open_parsec_text

    fh, opened = open_parsec_text(source)
    try:
        header = []
        for _ in range(40):
            line = fh.readline()
            if not line:
                break
            if line.startswith("#"):
                header.append(line)
            if "isochrones based on PARSEC release" in line:
                return True
                # fall through: also accept any comment line with M_ini/M_act
        for line in header:
            tokens = line.lstrip("#").split()
            if "M_ini" in tokens and "M_act" in tokens:
                return True
        return False
    except (OSError, UnicodeDecodeError):
        return False
    finally:
        if opened:
            fh.close()


def parsec_identity(facts: dict) -> ModelIdentity:
    release = facts.get("release") or "unknown"
    # collapse the release string into a compact physics configuration tag
    physics = release.replace(" + ", "+").replace("  ", " ")
    return ModelIdentity(
        family="parsec",
        release=release,
        product="cmd_isochrone_table",
        physics_configuration=physics,
        description=(
            "CMD web-interface isochrone table: PARSEC tracks (PMS to first "
            "TP or C-ignition) extended by COLIBRI TP-AGB, with photometry "
            "in the photometric system stated in the header"
        ),
    )


def parsec_parameters(facts: dict, block_z, log_ages) -> tuple:
    """ParameterSpecs for one CMD isochrone table.

    Static knowledge (roles, the v1.2S helium enrichment law, the
    not-applicable rotation) comes from the unified-parameter registry;
    the file supplies the age list, the per-block Z values when the
    header states them, and the Reimers eta when present.
    """
    dynamic = {"log_age": tuple(sorted(set(log_ages)))}
    z_values = {z for z in block_z if z is not None}
    if z_values:
        dynamic["initial_z"] = tuple(sorted(z_values))
    if facts.get("eta_reimers") is not None:
        dynamic["eta_reimers"] = facts["eta_reimers"]
    return resolve_parameters("parsec", "cmd_table", dynamic)


def read_parsec(
    source: str | os.PathLike | TextIO,
    provenance: Provenance | None = None,
) -> IsochroneSet:
    parsed: ParsecFile = parse_parsec_cmd(source)
    native = parsed.native
    facts = parsed.facts
    identity = parsec_identity(facts)

    params = parsec_parameters(
        facts, [b.z for b in parsed.blocks], facts["ages"]
    )

    prov = provenance if provenance is not None else Provenance()
    if not prov.scientific_references:
        prov = Provenance(
            data_sources=prov.data_sources,
            assets=prov.assets,
            source_chains=prov.source_chains,
            scientific_references=PARSEC_REFERENCES,
            software_references=prov.software_references,
            transformations=prov.transformations,
        )

    isochrones = []
    for block, meta in zip(parsed.blocks, native.block_metadata):
        selection = {"log_age": meta["log_age"]}
        if meta.get("z") is not None:
            selection["initial_z"] = meta["z"]
        block_native = NativeTable(
            table=native.table[block.row_start : block.row_stop],
            header=block.header_lines,
            metadata=dict(native.metadata),
            block_metadata=(dict(meta),),
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
