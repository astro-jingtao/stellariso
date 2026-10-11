"""Isochrone and IsochroneSet: the per-isochrone and per-file objects.

An :class:`Isochrone` is one theoretical isochrone — a fixed age, a fixed
composition and physics configuration — exposing both the native table it
was sliced from and the unified view mapped onto it. An
:class:`IsochroneSet` is every isochrone that came out of one file or data
product; a file is rarely a single isochrone, so this layer always exists.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
from astropy.table import Table

from .core import FieldSpec, ModelIdentity, ParameterSpec
from .native import NativeTable
from .provenance import Provenance

__all__ = ["Isochrone", "IsochroneSet"]


class Isochrone:
    """One isochrone: a native row-slice plus its unified view.

    Instances are constructed by backends, not directly by users. The
    ``unified`` accessor and convenience attributes are provided by the
    backend's unified machinery (see ``stellariso.unified``); this class
    holds the pieces and the metadata that travels with them.
    """

    def __init__(
        self,
        native: NativeTable,
        identity: ModelIdentity,
        parameters: tuple[ParameterSpec, ...] = (),
        field_specs: Mapping[str, FieldSpec] | None = None,
        provenance: Provenance | None = None,
        selection: Mapping[str, Any] | None = None,
        unified_view: Any = None,
    ):
        self._native = native
        self.identity = identity
        self.parameters = tuple(parameters)
        self.field_specs: Mapping[str, FieldSpec] = dict(field_specs or {})
        self.provenance = provenance if provenance is not None else Provenance()
        self.selection: Mapping[str, Any] = dict(selection or {})
        self._unified_view = unified_view

    # -- layers ------------------------------------------------------------

    @property
    def native(self) -> NativeTable:
        return self._native

    @property
    def unified(self):
        if self._unified_view is None:
            raise AttributeError(
                "no unified view is attached; the backend that produced this "
                "isochrone did not build one"
            )
        return self._unified_view

    # -- parameter access ----------------------------------------------------

    def parameter(self, name: str) -> ParameterSpec:
        for spec in self.parameters:
            if spec.name == name:
                return spec
        raise KeyError(f"no parameter named {name!r}")

    # -- unified field access -------------------------------------------------

    def get(self, name: str):
        """Unified field values (same as ``self.unified[name]``)."""
        return self.unified[name]

    def has_field(self, name: str) -> bool:
        return name in self.field_specs

    def field_info(self, name: str) -> FieldSpec:
        """The FieldSpec tracing unified field ``name`` back to native data."""
        try:
            return self.field_specs[name]
        except KeyError:
            raise KeyError(
                f"no unified field {name!r}; available: {sorted(self.field_specs)}"
            ) from None

    def __getattr__(self, name: str):
        # called only when normal attribute lookup fails; expose unified
        # fields as attributes (iso.log_surface_gravity, iso.initial_mass...)
        specs = object.__getattribute__(self, "field_specs")
        if name in specs:
            return object.__getattribute__(self, "unified")[name]
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )

    def parameter_value(self, name: str) -> Any:
        """The scalar value of a parameter for this isochrone.

        Only meaningful for parameters that are constant across the set
        (fixed/implicit roles, or an axis parameter pinned by the selection);
        axis parameters without a pinned value raise.
        """
        spec = self.parameter(name)
        if spec.role.value == "axis":
            pinned = self.selection.get(name)
            if pinned is None:
                raise KeyError(
                    f"parameter {name!r} is a grid axis; its value for this "
                    "isochrone lives in the selection metadata, which does "
                    "not pin it"
                )
            return pinned
        if spec.value is not None:
            return spec.value
        if spec.status is not None:
            raise KeyError(f"parameter {name!r} status: {spec.status}")
        raise KeyError(f"parameter {name!r} carries no value")

    # -- export ------------------------------------------------------------

    def to_table(self, layer: str = "unified") -> Table:
        """Return the isochrone as an astropy Table in the chosen layer."""
        if layer == "native":
            return self._native.table
        if layer == "unified":
            return self.unified.to_table()
        raise ValueError(f"layer must be 'native' or 'unified', got {layer!r}")

    def __len__(self) -> int:
        return len(self._native)

    def __repr__(self) -> str:
        return (
            f"Isochrone({self.identity.label}, {len(self)} points, "
            f"{len(self.parameters)} parameters)"
        )


class IsochroneSet:
    """All isochrones from one file or data product.

    The set keeps the file-level native table intact (the per-isochrone
    slices reference it, they do not copy it) and provides lookup by the
    coordinates the backend defines (for MIST: log10 age; in general:
    whatever the product varies within one file).
    """

    def __init__(
        self,
        isochrones: tuple[Isochrone, ...],
        native: NativeTable,
        identity: ModelIdentity,
        parameters: tuple[ParameterSpec, ...] = (),
        provenance: Provenance | None = None,
        indexer: str | None = None,
    ):
        self._isochrones = tuple(isochrones)
        self._native = native
        self.identity = identity
        self.parameters = tuple(parameters)
        self.provenance = provenance if provenance is not None else Provenance()
        self.indexer = indexer

    @property
    def isochrones(self) -> tuple[Isochrone, ...]:
        return self._isochrones

    @property
    def native(self) -> NativeTable:
        return self._native

    def __len__(self) -> int:
        return len(self._isochrones)

    def __iter__(self):
        return iter(self._isochrones)

    def __getitem__(self, idx):
        return self._isochrones[idx]

    def keys(self):
        """Index coordinates of the member isochrones (e.g. the log ages)."""
        return [iso.selection.get(self.indexer) for iso in self._isochrones]

    def parameter(self, name: str) -> ParameterSpec:
        for spec in self.parameters:
            if spec.name == name:
                return spec
        raise KeyError(f"no parameter named {name!r}")

    def __repr__(self) -> str:
        n = len(self._isochrones)
        keys = self.keys()
        span = f"{keys[0]}..{keys[-1]}" if keys and keys[0] is not None else "?"
        return f"IsochroneSet({self.identity.label}, {n} isochrones, {span})"
