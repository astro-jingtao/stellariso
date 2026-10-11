"""PARSEC backend: identity, parameters, IsochroneSet construction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO

from ...core import ModelIdentity, ParameterRole, ParameterSource, ParameterSpec
from ...isochrone import Isochrone, IsochroneSet
from ...native import NativeTable
from ...provenance import Provenance, Reference
from ...unified import UnifiedView
from .mappings import PARSEC_FIELD_SPECS, PARSEC_PHASE_MAPPING
from .reader import ParsecFile, parse_parsec_cmd

__all__ = ["read_parsec", "recognize_parsec", "PARSEC_REFERENCES"]

PARSEC_REFERENCES = (
    Reference(
        citation="Bressan, A., Marigo, P., Girardi, L., et al. 2012, MNRAS, 427, 127",
        bibcode="2012MNRAS.427..127B",
        ads_url="https://ui.adsabs.harvard.edu/abs/2012MNRAS.427..127B",
    ),
    Reference(
        citation="Marigo, P., Bressan, A., Nanni, A., Girardi, L., Pumo, M. L. "
        "2013, MNRAS, 434, 488",
        bibcode="2013MNRAS.434..488M",
    ),
    Reference(
        citation="Marigo, P., Girardi, L., Bressan, A., et al. 2017, ApJ, 835, 77",
        bibcode="2017ApJ...835...77M",
    ),
    Reference(
        citation="Chen, Y., Girardi, L., Bressan, A., et al. 2014, MNRAS, 444, 2525 "
        "and 2015, MNRAS, 452, 1068",
    ),
    Reference(
        citation="Pastorelli, G., et al. 2019, MNRAS, 485, 5666 and 2020, MNRAS",
    ),
)

_FIELD_SPEC_DICT = {spec.name: spec for spec in PARSEC_FIELD_SPECS}


def recognize_parsec(source: str | os.PathLike | TextIO) -> bool:
    """Cheap sniff for CMD isochrone tables (header + column signature)."""
    from .reader import open_parsec_text

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


def parsec_parameters(facts: dict, block_z, log_ages) -> tuple[ParameterSpec, ...]:
    specs = [
        ParameterSpec(
            name="log_age",
            role=ParameterRole.AXIS,
            values=tuple(sorted(set(log_ages))),
            unit="dex(log10(age/yr))",
            source=ParameterSource.NATIVE,
        ),
    ]
    z_values = {z for z in block_z if z is not None}
    if z_values:
        specs.append(
            ParameterSpec(
                name="initial_z",
                role=ParameterRole.AXIS,
                values=tuple(sorted(z_values)),
                source=ParameterSource.NATIVE,
                description="initial metal mass fraction as stated by the "
                "per-isochrone header lines",
            )
        )
    else:
        specs.append(
            ParameterSpec(
                name="initial_z",
                role=ParameterRole.IMPLICIT,
                status="not_in_file",
                description="CMD tables do not restate Z per file; recover it "
                "from the generating request (see provenance) or the block "
                "headers",
            )
        )
    specs.extend(
        [
            ParameterSpec(
                name="initial_helium",
                role=ParameterRole.DERIVED,
                depends_on=("initial_z",),
                relation="Y_p + dYdZ * initial_z",
                relation_parameters={"Y_p": 0.2485, "dYdZ": 1.78},
                source=ParameterSource.DERIVED_FROM_OFFICIAL_RELATION,
                description="scaled-solar helium enrichment law of the "
                "PARSEC v1.2S grid (stated on the CMD form)",
            ),
            ParameterSpec(
                name="alpha_fe",
                role=ParameterRole.FIXED,
                value=0.0,
                unit="dex",
                source=ParameterSource.OFFICIAL_DOCUMENTATION,
                description="scaled-solar (CAF09) composition; the CMD v1.2S "
                "products carry no alpha enhancement",
            ),
            ParameterSpec(
                name="initial_rotation",
                role=ParameterRole.NOT_APPLICABLE,
                description="PARSEC v1.2S tracks are non-rotating; rotation "
                "exists only in the PARSEC v2.0 products",
            ),
        ]
    )
    if facts.get("eta_reimers") is not None:
        specs.append(
            ParameterSpec(
                name="eta_reimers",
                role=ParameterRole.FIXED,
                value=facts["eta_reimers"],
                source=ParameterSource.NATIVE,
                description="RGB Reimers mass-loss efficiency (file header)",
            )
        )
    specs.append(
        ParameterSpec(name="mixing_length", role=ParameterRole.IMPLICIT,
                      status="not_reported")
    )
    return tuple(specs)


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
                    block_native, _FIELD_SPEC_DICT, PARSEC_PHASE_MAPPING
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
