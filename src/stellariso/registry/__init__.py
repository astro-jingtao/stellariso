"""Declarative unified-parameter registry.

The JSON file next to this module is the single source of truth for the
unified vocabulary (fields, coarse stages, physical parameters) and for each
backend's mapping into it. The human-readable document
``docs/unified-parameters.md`` is generated from that file by
``tools/generate_parameter_docs.py`` — edit the JSON, regenerate the doc,
never the other way round.

Backends read their field specs, phase mappings, static parameter knowledge,
and literature references from here; only values that come from the data
files themselves are injected at read time through ``resolve_parameters``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from stellariso.core import (
    FieldOrigin,
    FieldSpec,
    ParameterRole,
    ParameterSource,
    ParameterSpec,
)

_REGISTRY_FILE = Path(__file__).with_name("unified_parameters.json")

__all__ = [
    "load_registry",
    "unified_field_names",
    "unified_phases",
    "backend_names",
    "field_specs",
    "field_spec_dict",
    "phase_mapping",
    "resolve_parameters",
    "references",
    "backend_notes",
    "phase_code_meanings",
    "eep_anchors",
    "REGISTRY_FILE",
]

REGISTRY_FILE = _REGISTRY_FILE


@lru_cache(maxsize=1)
def _registry() -> dict:
    with open(_REGISTRY_FILE, encoding="utf-8") as fh:
        reg = json.load(fh)
    _validate(reg)
    return reg


def load_registry() -> dict:
    """The parsed registry (read-only by convention; callers must not mutate)."""
    return _registry()


def _validate(reg: dict) -> None:
    fields = {f["name"] for f in reg["unified_fields"]}
    if len(fields) != len(reg["unified_fields"]):
        raise ValueError("unified_fields contains duplicate names")
    stages = set(reg["unified_phases"])
    known_params = {p["name"] for p in reg["physical_parameters"]}
    for name, backend in reg["backends"].items():
        for mapping in backend["field_mappings"]:
            if mapping["unified"] not in fields:
                raise ValueError(
                    f"backend {name!r} maps unknown unified field "
                    f"{mapping['unified']!r}"
                )
            if FieldOrigin(mapping["origin"]) is FieldOrigin.TRANSFORMED_NATIVE:
                from stellariso.unified import TRANSFORMATIONS

                if mapping.get("transformation") not in TRANSFORMATIONS:
                    raise ValueError(
                        f"backend {name!r} field {mapping['unified']!r} uses "
                        f"transformation {mapping.get('transformation')!r}, "
                        "which the unified view does not implement"
                    )
        for stage in backend["phase_mapping"].values():
            if stage not in stages:
                raise ValueError(
                    f"backend {name!r} maps to non-standard stage {stage!r}"
                )
        for key in backend["phase_mapping"]:
            int(key)  # phase codes must be integers
        for entry in backend["parameters"]:
            if entry["name"] not in known_params:
                raise ValueError(
                    f"backend {name!r} declares unknown physical parameter "
                    f"{entry['name']!r}"
                )


def _backend(name: str) -> dict:
    try:
        return _registry()["backends"][name.lower()]
    except KeyError:
        known = sorted(_registry()["backends"])
        raise ValueError(
            f"no backend {name!r} in the unified registry; known: {known}"
        ) from None


def backend_names() -> tuple[str, ...]:
    return tuple(_registry()["backends"])


def unified_field_names() -> tuple[str, ...]:
    return tuple(f["name"] for f in _registry()["unified_fields"])


def unified_phases() -> tuple[str, ...]:
    return tuple(_registry()["unified_phases"])


# -- field mappings -----------------------------------------------------------


def field_specs(backend: str) -> tuple[FieldSpec, ...]:
    """The backend's unified field specs, built from the registry.

    Units and representation come from the unified vocabulary (one place);
    a mapping adds the native column, origin, transformation, and any
    backend-specific description.
    """
    be = _backend(backend)
    vocab = {f["name"]: f for f in _registry()["unified_fields"]}
    specs = []
    for mapping in be["field_mappings"]:
        v = vocab[mapping["unified"]]
        specs.append(
            FieldSpec(
                name=mapping["unified"],
                native_name=mapping["native"],
                unit=v["unit"],
                native_unit=mapping.get("native_unit", v["unit"]),
                representation=v["representation"],
                origin=FieldOrigin(mapping["origin"]),
                transformation=mapping.get("transformation"),
                description=mapping.get("description", v.get("description")),
                backend=backend.lower(),
                mapping_version=be["mapping_version"],
            )
        )
    return tuple(specs)


def field_spec_dict(backend: str) -> dict[str, FieldSpec]:
    return {spec.name: spec for spec in field_specs(backend)}


def phase_mapping(backend: str):
    """The backend's versioned native-phase-code -> unified-stage mapping."""
    from stellariso.unified import PhaseMapping

    be = _backend(backend)
    table = {int(k): v for k, v in be["phase_mapping"].items()}
    return PhaseMapping(
        backend=backend.lower(), version=be["mapping_version"], table=table
    )


def phase_code_meanings(backend: str) -> dict[int, str]:
    """Official meaning of each native phase code (documentation)."""
    return {int(k): v for k, v in _backend(backend)["phase_code_meanings"].items()}


def eep_anchors(backend: str) -> dict[str, int] | None:
    """Primary EEP anchor points when the backend defines them (MIST)."""
    return _backend(backend).get("eep_anchors")


# -- physical parameters ------------------------------------------------------


def _when_passes(when: Mapping[str, str], dynamic: Mapping[str, Any]) -> bool:
    if "available" in when:
        return when["available"] in dynamic
    if "missing" in when:
        return when["missing"] not in dynamic
    raise ValueError(f"unknown when condition {dict(when)!r}")


def _choose(entry: dict, dynamic: Mapping[str, Any]) -> dict | None:
    """Resolve an entry's variants against the reader-supplied values.

    ``when`` on the entry itself gates the whole entry; ``alternatives``
    are tried in order, the first whose ``when`` passes wins, and an
    alternative without ``when`` always passes (put it last as fallback).
    """
    when = entry.get("when")
    if when is not None and not _when_passes(when, dynamic):
        return None
    if "alternatives" in entry:
        for alt in entry["alternatives"]:
            alt_when = alt.get("when")
            if alt_when is None or _when_passes(alt_when, dynamic):
                return alt
        return None
    return entry


def _spec_from_entry(
    name: str, chosen: Mapping[str, Any], dynamic: Mapping[str, Any]
) -> ParameterSpec:
    vocab = {p["name"]: p for p in _registry()["physical_parameters"]}[name]
    kwargs: dict[str, Any] = {}
    for key in ("unit", "convention", "description", "status"):
        value = chosen.get(key, vocab.get(key))
        if value is not None:
            kwargs[key] = value
    if "source" in chosen:
        kwargs["source"] = ParameterSource(chosen["source"])
    if "depends_on" in chosen:
        kwargs["depends_on"] = tuple(chosen["depends_on"])
    if "relation" in chosen:
        kwargs["relation"] = chosen["relation"]
    if "relation_parameters" in chosen:
        kwargs["relation_parameters"] = dict(chosen["relation_parameters"])

    if "value_from" in chosen:
        key = chosen["value_from"]
        if key not in dynamic:
            raise KeyError(
                f"parameter {name!r} wants value_from {key!r}, which the "
                "reader did not supply"
            )
        kwargs["value"] = dynamic[key]
    elif "value" in chosen:
        kwargs["value"] = chosen["value"]

    if "values_from" in chosen:
        key = chosen["values_from"]
        if key not in dynamic:
            raise KeyError(
                f"parameter {name!r} wants values_from {key!r}, which the "
                "reader did not supply"
            )
        kwargs["values"] = tuple(dynamic[key])
    elif "values" in chosen:
        kwargs["values"] = tuple(chosen["values"])

    return ParameterSpec(name=name, role=ParameterRole(chosen["role"]), **kwargs)


def resolve_parameters(
    backend: str, dynamic: Mapping[str, Any]
) -> tuple[ParameterSpec, ...]:
    """Build the backend's ParameterSpecs from registry templates.

    ``dynamic`` carries the values only the data file knows, keyed by
    parameter name (e.g. ``{"log_age": (9.0, 9.5), "initial_z": 0.0152}``);
    everything static (roles, relations, implicit parameters) comes from
    the registry. Omitting a key selects the registry's fallback variant
    for parameters that declare one, and is an error for parameters whose
    value must come from the file.
    """
    be = _backend(backend)
    specs = []
    for entry in be["parameters"]:
        chosen = _choose(entry, dynamic)
        if chosen is None:
            continue
        specs.append(_spec_from_entry(entry["name"], chosen, dynamic))
    return tuple(specs)


# -- references and notes -----------------------------------------------------


def references(backend: str) -> tuple:
    """The backend's scientific references (what to cite)."""
    from stellariso.provenance import Reference

    be = _backend(backend)
    return tuple(Reference(**ref) for ref in be["references"])


def backend_notes(backend: str) -> tuple[str, ...]:
    """Documented caveats of the backend's mapping (from official docs)."""
    return tuple(_backend(backend)["notes"])
