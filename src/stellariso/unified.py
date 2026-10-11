"""Unified layer: a traceable, lazily-computed view over native tables.

The unified view renames a product's columns to canonical field names and
computes documented transformations, but it is not a second copy of the data:
native columns are referenced, transformed columns are computed on demand,
and every field carries its :class:`~stellariso.core.FieldSpec` describing
exactly how it maps back to native data.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np
from astropy.table import Table
from astropy import units as u

from stellariso.core import FieldOrigin, FieldSpec
from stellariso.native import NativeTable
from stellariso.registry import unified_phases
from stellariso.warnings import PhaseMappingWarning

import warnings

__all__ = ["UnifiedView", "PhaseMapping", "TRANSFORMATIONS", "UNIFIED_PHASES"]

# Transformations are a fixed, named vocabulary — never free-form code.
# A FieldSpec's `transformation` string must be one of these.
TRANSFORMATIONS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "10 ** x": lambda a: np.power(10.0, a),
}

# Coarse unified evolutionary stages — the allowed vocabulary, declared in
# the unified-parameter registry (see stellariso.registry).
UNIFIED_PHASES = unified_phases()


class PhaseMapping:
    """A versioned, disablable mapping from native phase codes to unified
    stage names. Unmapped codes resolve to ``"unknown"`` with a warning,
    never to a guess."""

    def __init__(
        self,
        backend: str,
        version: str,
        table: Mapping[Any, str],
        unmapped: str = "unknown",
    ):
        self.backend = backend
        self.version = version
        self.table = dict(table)
        self.unmapped = unmapped
        unknown_values = set(self.table.values()) - set(UNIFIED_PHASES)
        if unknown_values:
            raise ValueError(
                f"phase mapping for {backend!r} uses non-standard stage names: "
                f"{sorted(unknown_values)}"
            )

    def __call__(self, codes: np.ndarray) -> np.ndarray:
        out = np.full(len(codes), self.unmapped, dtype=object)
        seen_unmapped = set()
        for i, code in enumerate(codes):
            key = int(code) if float(code).is_integer() else code
            stage = self.table.get(key)
            if stage is None:
                seen_unmapped.add(code)
                stage = self.unmapped
            out[i] = stage
        if seen_unmapped:
            warnings.warn(
                f"{len(seen_unmapped)} distinct native phase code(s) of backend "
                f"{self.backend!r} have no unified mapping "
                f"({sorted(seen_unmapped)[:10]}); mapped to "
                f"{self.unmapped!r}",
                PhaseMappingWarning,
                stacklevel=2,
            )
        return out


class UnifiedView:
    """Lazy unified access over one native table.

    ``view[name]`` returns the unified field's values (native column when
    the origin is native, the documented transformation when it is not).
    ``to_table()`` materializes the unified layer as an astropy Table.
    """

    def __init__(
        self,
        native: NativeTable,
        field_specs: Mapping[str, FieldSpec],
        phase_mapping: PhaseMapping | None = None,
    ):
        self._native = native
        self._specs = dict(field_specs)
        self._phase_mapping = phase_mapping

    @property
    def field_names(self) -> list[str]:
        return list(self._specs)

    def field_spec(self, name: str) -> FieldSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise KeyError(
                f"no unified field {name!r}; available: {self.field_names}"
            ) from None

    def has_field(self, name: str) -> bool:
        return name in self._specs

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __getitem__(self, name: str) -> np.ndarray:
        spec = self.field_spec(name)
        if spec.origin is FieldOrigin.MISSING:
            raise KeyError(f"unified field {name!r} is not available in this product")
        if spec.native_name is None:
            raise KeyError(
                f"unified field {name!r} has no native source declared"
            )
        values = np.asarray(self._native[spec.native_name])
        if spec.origin is FieldOrigin.NATIVE:
            return values
        if spec.origin is FieldOrigin.TRANSFORMED_NATIVE:
            try:
                fn = TRANSFORMATIONS[spec.transformation]
            except KeyError:
                raise NotImplementedError(
                    f"transformation {spec.transformation!r} of field {name!r} "
                    "is documented but not implemented"
                ) from None
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                return fn(values)
        # derived: only the phase mapping is currently derivable
        if name == "phase" and self._phase_mapping is not None:
            return self._phase_mapping(values)
        raise NotImplementedError(
            f"derived field {name!r} has no computation rule in the unified view"
        )

    def to_table(self) -> Table:
        cols = {}
        meta = {
            "stellariso_layer": "unified",
            "field_specs": {n: s.to_dict() for n, s in self._specs.items()},
        }
        if self._phase_mapping is not None:
            meta["phase_mapping"] = {
                "backend": self._phase_mapping.backend,
                "version": self._phase_mapping.version,
            }
        for name in self.field_names:
            spec = self._specs[name]
            if spec.origin is FieldOrigin.MISSING:
                continue
            col = self[name]
            cols[name] = col
        table = Table(cols, meta=meta)
        for name, spec in self._specs.items():
            if name not in table.colnames or spec.unit is None:
                continue
            try:
                table[name].unit = u.Unit(spec.unit)
            except ValueError:
                # keep the string in meta rather than inventing a unit
                pass
        return table
