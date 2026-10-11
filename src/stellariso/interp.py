"""Conservative interpolation within a single isochrone.

Rules (v1):

- Interpolation runs along one coordinate column of the isochrone
  (``initial_mass`` by default) and only within that one isochrone — never
  across ages or compositions.
- The coordinate must be non-decreasing after deduplication of exact ties;
  otherwise :class:`UnsafeInterpolationError` (some models' late phases
  reverse in mass — the user must then choose another coordinate).
- No extrapolation: requests outside the coordinate range raise
  :class:`UnsafeInterpolationError`.
- Results carry an :class:`InterpolationRecord` stating the method, the
  bracketing nodes, and the native phases of those nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import numpy as np
from scipy.interpolate import PchipInterpolator

from .exceptions import UnsafeInterpolationError
from .isochrone import Isochrone

__all__ = ["InterpolationRecord", "interpolate_along", "interp_methods"]

_METHODS = ("linear", "pchip")


def interp_methods() -> tuple[str, ...]:
    return _METHODS


@dataclass(frozen=True)
class InterpolationRecord:
    """Everything needed to audit one interpolation."""

    coordinate: str
    method: str
    requested: tuple[float, ...]
    node_indices: tuple[tuple[int, int], ...]  # bracketing rows (native table)
    node_values: tuple[tuple[float, float], ...]  # coordinate at those rows
    node_phases: tuple[tuple[Any, Any], ...]  # native phase codes
    fields: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "method": self.method,
            "requested": list(self.requested),
            "node_indices": [list(pair) for pair in self.node_indices],
            "node_values": [list(pair) for pair in self.node_values],
            "node_phases": [list(pair) for pair in self.node_phases],
            "fields": list(self.fields),
        }


def _prepare_coordinate(iso: Isochrone, coordinate: str):
    # the coordinate may be a unified field name (initial_mass) or a native
    # column name; both must be numeric and monotone-usable
    if coordinate in iso.field_specs:
        values = np.asarray(iso.unified[coordinate], dtype=float)
    elif coordinate in iso.native:
        values = np.asarray(iso.native[coordinate], dtype=float)
    else:
        raise KeyError(
            f"coordinate {coordinate!r} is neither a unified field nor a "
            f"native column of this isochrone"
        )
    # deduplicate exact/rounded ties, keeping the first occurrence
    keep = np.concatenate([[True], np.diff(values) > 1e-12])
    if not np.all(np.diff(values[keep]) > 0):
        raise UnsafeInterpolationError(
            f"coordinate {coordinate!r} is not non-decreasing along this "
            "isochrone even after tie deduplication; choose another "
            "coordinate (late phases of some models reverse in mass)"
        )
    return values, values[keep], np.flatnonzero(keep)


def _brackets(unique_values: np.ndarray, queries: np.ndarray):
    idx = np.searchsorted(unique_values, queries, side="left")
    # clamp into interior pairs; equality at endpoints handled below
    lo = np.clip(idx - 1, 0, len(unique_values) - 2)
    hi = lo + 1
    return lo, hi


def interpolate_along(
    iso: Isochrone,
    coordinate: str,
    values_query: Iterable[float] | float,
    fields: Iterable[str] | str,
    method: str = "linear",
) -> tuple[dict[str, np.ndarray], InterpolationRecord]:
    """Interpolate ``fields`` at given ``coordinate`` values within ``iso``."""
    if method not in _METHODS:
        raise ValueError(f"method must be one of {_METHODS}, got {method!r}")
    queries = np.atleast_1d(np.asarray(list(values_query) if np.ndim(values_query) else values_query, dtype=float))
    fields = [fields] if isinstance(fields, str) else list(fields)

    raw_values, unique_values, unique_rows = _prepare_coordinate(iso, coordinate)

    lo, hi = _brackets(unique_values, queries)
    inside = (queries >= unique_values[0]) & (queries <= unique_values[-1])
    if not np.all(inside):
        bad = queries[~inside]
        raise UnsafeInterpolationError(
            f"queried {coordinate} values {bad[:5]} fall outside the "
            f"isochrone range [{unique_values[0]}, {unique_values[-1]}]; "
            "extrapolation is not performed"
        )

    phases = np.asarray(iso.native["phase"]) if "phase" in iso.native else None

    out: dict[str, np.ndarray] = {}
    for name in fields:
        # unified field names take precedence; native column names also work
        if name in iso.field_specs:
            column = np.asarray(iso.unified[name], dtype=float)
        elif name in iso.native:
            column = np.asarray(iso.native[name], dtype=float)
        else:
            raise KeyError(
                f"field {name!r} is neither a unified field "
                f"({sorted(iso.field_specs)}) nor a native column "
                f"({iso.native.columns})"
            )
        if method == "linear":
            out[name] = np.interp(queries, unique_values, column[unique_rows])
        else:  # pchip
            spline = PchipInterpolator(unique_values, column[unique_rows])
            out[name] = spline(queries)

    node_indices = []
    node_values = []
    node_phases = []
    for q in queries:
        i = int(np.searchsorted(unique_values, q, side="right")) - 1
        i = min(max(i, 0), len(unique_values) - 2)
        j = i + 1
        ri, rj = int(unique_rows[i]), int(unique_rows[j])
        node_indices.append((ri, rj))
        node_values.append((float(unique_values[i]), float(unique_values[j])))
        node_phases.append(
            (phases[ri].item() if phases is not None else None,
             phases[rj].item() if phases is not None else None)
        )

    record = InterpolationRecord(
        coordinate=coordinate,
        method=method,
        requested=tuple(float(q) for q in queries),
        node_indices=tuple(node_indices),
        node_values=tuple(node_values),
        node_phases=tuple(node_phases),
        fields=tuple(fields),
    )
    return out, record
