"""Declarative unified-parameter registry.

The JSON file next to this module is the single source of truth for the
unified vocabulary (fields, coarse stages, physical parameters) and for each
backend's products — each product (an isochrone table format, a track
format) declares its own field mappings, phase mappings, and static
parameter knowledge. The human-readable document
``docs/unified-parameters.md`` is generated from that file by
``tools/generate_parameter_docs.py`` — edit the JSON, regenerate the doc,
never the other way round.

Backends read their field specs, phase mappings, parameter templates, and
literature references from here; only values that come from the data files
themselves are injected at read time through ``resolve_parameters``.
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
    "product_names",
    "field_specs",
    "field_spec_dict",
    "phase_mapping",
    "phase_code_meanings",
    "eep_anchors",
    "resolve_parameters",
    "references",
    "backend_notes",
    "product_notes",
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
        for product_key, product in backend["products"].items():
            for mapping in product["field_mappings"]:
                if mapping["unified"] not in fields:
                    raise ValueError(
                        f"backend {name!r} product {product_key!r} maps unknown "
                        f"unified field {mapping['unified']!r}"
                    )
                origin = FieldOrigin(mapping["origin"])
                if origin is FieldOrigin.TRANSFORMED_NATIVE:
                    from stellariso.unified import TRANSFORMATIONS

                    if mapping.get("transformation") not in TRANSFORMATIONS:
                        raise ValueError(
                            f"backend {name!r} product {product_key!r} field "
                            f"{mapping['unified']!r} uses transformation "
                            f"{mapping.get('transformation')!r}, which the "
                            "unified view does not implement"
                        )
                if origin not in (
                    FieldOrigin.NATIVE,
                    FieldOrigin.TRANSFORMED_NATIVE,
                ) and mapping.get("native") is not None:
                    # 'native' names the source column(s); 'native_name' on
                    # the FieldSpec is filled from it verbatim
                    pass
            for pm_key in ("phase_mapping", "hb_phase_mapping"):
                for key, stage in product.get(pm_key, {}).items():
                    int(key)  # phase codes must be integers
                    if stage not in stages:
                        raise ValueError(
                            f"backend {name!r} product {product_key!r} "
                            f"{pm_key} maps to non-standard stage {stage!r}"
                        )
            for entry in product["parameters"]:
                if entry["name"] not in known_params:
                    raise ValueError(
                        f"backend {name!r} product {product_key!r} declares "
                        f"unknown physical parameter {entry['name']!r}"
                    )


def _backend(name: str) -> dict:
    try:
        return _registry()["backends"][name.lower()]
    except KeyError:
        known = sorted(_registry()["backends"])
        raise ValueError(
            f"no backend {name!r} in the unified registry; known: {known}"
        ) from None


def _product(backend: str, product: str) -> dict:
    be = _backend(backend)
    products = be["products"]
    key = product.lower()
    try:
        return products[key]
    except KeyError:
        raise ValueError(
            f"backend {backend!r} has no product {product!r}; "
            f"known: {sorted(products)}"
        ) from None


def backend_names() -> tuple[str, ...]:
    return tuple(_registry()["backends"])


def product_names(backend: str) -> tuple[str, ...]:
    return tuple(_backend(backend)["products"])


def unified_field_names() -> tuple[str, ...]:
    return tuple(f["name"] for f in _registry()["unified_fields"])


def unified_phases() -> tuple[str, ...]:
    return tuple(_registry()["unified_phases"])


# -- field mappings -----------------------------------------------------------


def field_specs(backend: str, product: str) -> tuple[FieldSpec, ...]:
    """The product's unified field specs, built from the registry.

    Units and representation come from the unified vocabulary (one place);
    a mapping adds the native column, origin, transformation, and any
    product-specific description.
    """
    be = _backend(backend)
    prod = _product(backend, product)
    vocab = {f["name"]: f for f in _registry()["unified_fields"]}
    specs = []
    for mapping in prod["field_mappings"]:
        if mapping["origin"] == "missing":
            specs.append(
                FieldSpec(
                    name=mapping["unified"],
                    unit=None,
                    representation="linear",
                    origin=FieldOrigin.MISSING,
                    transformation=None,
                    description=mapping.get("description"),
                    backend=backend.lower(),
                    mapping_version=be["mapping_version"],
                )
            )
            continue
        v = vocab[mapping["unified"]]
        native_unit = mapping.get("native_unit", v["unit"])
        specs.append(
            FieldSpec(
                name=mapping["unified"],
                native_name=mapping["native"],
                unit=v["unit"],
                native_unit=native_unit,
                representation=v["representation"],
                origin=FieldOrigin(mapping["origin"]),
                transformation=mapping.get("transformation"),
                description=mapping.get("description", v.get("description")),
                backend=backend.lower(),
                mapping_version=be["mapping_version"],
            )
        )
    return tuple(specs)


def field_spec_dict(backend: str, product: str) -> dict[str, FieldSpec]:
    return {spec.name: spec for spec in field_specs(backend, product)}


def phase_mapping(backend: str, product: str, variant: str = "standard"):
    """The product's versioned native-phase-code -> unified-stage mapping.

    ``variant`` selects between a product's declared mappings (PARSEC
    tracks: ``"standard"`` or ``"hb"`` for the post-flash files).
    """
    from stellariso.unified import PhaseMapping

    be = _backend(backend)
    prod = _product(backend, product)
    key = "phase_mapping" if variant == "standard" else f"{variant}_phase_mapping"
    if key not in prod:
        raise ValueError(
            f"product {backend}/{product} has no phase mapping variant "
            f"{variant!r}; declared: "
            f"{[k.removesuffix('_phase_mapping') for k in prod if k.endswith('phase_mapping')]}"
        )
    table = {int(k): v for k, v in prod[key].items()}
    return PhaseMapping(
        backend=f"{backend.lower()}/{product}", version=be["mapping_version"], table=table
    )


def phase_code_meanings(backend: str, product: str, variant: str = "standard") -> dict[int, str]:
    """Documented meaning of each native phase code."""
    prod = _product(backend, product)
    key = "phase_mapping" if variant == "standard" else f"{variant}_phase_mapping"
    meaning_key = key.replace("phase_mapping", "phase_code_meanings")
    return {int(k): v for k, v in prod.get(meaning_key, {}).items()}


def eep_anchors(backend: str, product: str) -> dict[str, int] | None:
    """Primary EEP anchor points when the product defines them (MIST)."""
    return _product(backend, product).get("eep_anchors")


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
    backend: str, product: str, dynamic: Mapping[str, Any]
) -> tuple[ParameterSpec, ...]:
    """Build the product's ParameterSpecs from registry templates.

    ``dynamic`` carries the values only the data files know, keyed by
    parameter name (e.g. ``{"log_age": (9.0, 9.5), "initial_z": 0.0152}``);
    everything static (roles, relations, implicit parameters) comes from
    the registry. Omitting a key selects the registry's fallback variant
    for parameters that declare one, and is an error for parameters whose
    value must come from the file.
    """
    prod = _product(backend, product)
    specs = []
    for entry in prod["parameters"]:
        chosen = _choose(entry, dynamic)
        if chosen is None:
            continue
        specs.append(_spec_from_entry(entry["name"], chosen, dynamic))
    return tuple(specs)


# -- references and notes -----------------------------------------------------


def references(backend: str) -> tuple:
    """The backend family's scientific references (what to cite)."""
    from stellariso.provenance import Reference

    be = _backend(backend)
    return tuple(Reference(**ref) for ref in be["references"])


def backend_notes(backend: str) -> tuple[str, ...]:
    """Documented caveats shared by the backend's products."""
    return tuple(_backend(backend)["notes"])


def product_notes(backend: str, product: str) -> tuple[str, ...]:
    """Documented caveats of one product's mapping."""
    return tuple(_product(backend, product).get("notes", ()))
