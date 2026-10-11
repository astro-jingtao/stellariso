"""IsochroneGrid and open_grid: queryable collections of isochrone sets.

A grid holds every isochrone read from one product (one file or a directory
of files of the same model, release, and physics configuration). Selection
supports ``exact`` (fail loudly when absent) and ``nearest`` (warn, record
requested vs returned values and distances). Cross-isochrone interpolation
in age or composition is deliberately not provided.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from stellariso.exceptions import (
    AmbiguousFormatError,
    GridPointNotFoundError,
    UnrecognizedFormatError,
)
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.models import get_backend
from stellariso.warnings import NearestGridPointWarning

__all__ = ["IsochroneGrid", "open_grid"]

_SELECTABLE_FALLBACK = ("log_age",)


class IsochroneGrid:
    """All isochrones of one model product, queryable by grid coordinates.

    The selectable coordinates are derived from the keys the backend pinned
    in each isochrone's selection metadata (MIST: log_age, initial_feh,
    alpha_fe, initial_rotation; PARSEC: log_age, initial_z), so the grid
    stays model-agnostic.
    """

    def __init__(self, sets: Iterable[IsochroneSet]):
        self._sets = tuple(sets)
        if not self._sets:
            raise ValueError("an IsochroneGrid needs at least one IsochroneSet")
        identities = {s.identity for s in self._sets}
        if len(identities) > 1:
            raise ValueError(
                "cannot mix model products in one grid: "
                + "; ".join(i.label for i in identities)
            )
        self.identity = self._sets[0].identity
        self._isochrones: tuple[Isochrone, ...] = tuple(
            iso for s in self._sets for iso in s.isochrones
        )
        coords: list[str] = []
        for iso in self._isochrones:
            for k in iso.selection:
                if k not in coords:
                    coords.append(k)
        if "log_age" in coords:
            coords.remove("log_age")
            coords = ["log_age"] + coords
        self._selectable = tuple(coords) or _SELECTABLE_FALLBACK
        self._sets_by_key = {}
        for s in self._sets:
            for iso in s:
                key = self._key_of(iso)
                if key in self._sets_by_key:
                    raise ValueError(
                        f"duplicate isochrone at grid point {key}"
                    )
                self._sets_by_key[key] = iso

    # -- construction -------------------------------------------------------

    @classmethod
    def from_paths(cls, model: str, paths: Iterable[str | os.PathLike]) -> "IsochroneGrid":
        backend = get_backend(model)
        sets = [backend.read(p) for p in paths]
        return cls(sets)

    @classmethod
    def from_directory(
        cls, model: str, directory: str | os.PathLike, recursive: bool = True
    ) -> "IsochroneGrid":
        backend = get_backend(model)
        root = Path(directory)
        if not root.is_dir():
            raise NotADirectoryError(root)
        paths = sorted(
            p for p in (root.rglob("*") if recursive else root.glob("*"))
            if p.is_file() and not p.name.startswith(".")
        )
        readable = [p for p in paths if backend.recognize(p)]
        if not readable:
            raise UnrecognizedFormatError(
                f"no {model} isochrone files found under {root}"
            )
        return cls.from_paths(model, readable)

    # -- introspection ------------------------------------------------------

    @property
    def sets(self) -> tuple[IsochroneSet, ...]:
        return self._sets

    @property
    def isochrones(self) -> tuple[Isochrone, ...]:
        return self._isochrones

    def __len__(self) -> int:
        return len(self._isochrones)

    def __iter__(self):
        return iter(self._isochrones)

    def _key_of(self, iso: Isochrone) -> tuple:
        return tuple(iso.selection.get(k) for k in self._selectable)

    def axis_values(self, name: str) -> tuple:
        """Available values of a selection coordinate, sorted, unique."""
        idx = self._selectable.index(name)
        values = {key[idx] for key in self._sets_by_key}
        return tuple(sorted(values))

    @property
    def axes(self) -> dict[str, tuple]:
        return {name: self.axis_values(name) for name in self._selectable}

    @property
    def provenance(self):
        from stellariso.provenance import Provenance

        return Provenance(
            data_sources=tuple(
                src for s in self._sets for src in s.provenance.data_sources
            ),
            assets=tuple(a for s in self._sets for a in s.provenance.assets),
            source_chains=tuple(
                c for s in self._sets for c in s.provenance.source_chains
            ),
            scientific_references=self._sets[0].provenance.scientific_references,
            software_references=self._sets[0].provenance.software_references,
            transformations=tuple(
                t for s in self._sets for t in s.provenance.transformations
            ),
        )

    # -- selection ----------------------------------------------------------

    def get_isochrone(self, method: str = "exact", **coordinates) -> Isochrone:
        """Select one isochrone by grid coordinates.

        Parameters
        ----------
        method
            ``"exact"``: every requested coordinate must match an available
            grid point (``GridPointNotFoundError`` otherwise). ``"nearest"``:
            each coordinate snaps to the nearest available value
            (``NearestGridPointWarning`` when any snapping occurred).
        **coordinates
            Any of ``log_age``, ``initial_feh``, ``alpha_fe``,
            ``initial_rotation``; unspecified coordinates are unconstrained
            only when exactly one isochrone remains — otherwise the missing
            axes must be pinned.
        """
        if method not in ("exact", "nearest"):
            raise ValueError(f"method must be 'exact' or 'nearest', got {method!r}")

        requested = {k: float(v) for k, v in coordinates.items()}
        unknown = set(requested) - set(self._selectable)
        if unknown:
            raise ValueError(
                f"unknown selection coordinates {sorted(unknown)}; "
                f"selectable: {list(self._selectable)}"
            )

        if method == "exact":
            # unrequested coordinates default to the grid's value when the
            # axis is unique; multi-valued axes must be pinned explicitly
            filled = dict(requested)
            for name in self._selectable:
                if name in filled:
                    continue
                values = self.axis_values(name)
                if len(values) == 1:
                    filled[name] = values[0]
            still_missing = [
                k for k in self._selectable if k not in filled and len(self.axis_values(k)) > 1
            ]
            if still_missing:
                raise GridPointNotFoundError(
                    f"coordinates {still_missing} have several values in this "
                    f"grid and were not pinned; available axes: {self.axes}"
                )
            key = tuple(filled.get(k) for k in self._selectable)
            iso = self._sets_by_key.get(key)
            if iso is None:
                raise GridPointNotFoundError(
                    f"no isochrone at {filled}; available axes: {self.axes}"
                )
            return iso.with_selection_info(
                {"method": "exact", "requested": dict(requested), "returned": filled}
            )

        # nearest: snap each requested coordinate independently
        snapped = {}
        distances = {}
        for name, value in requested.items():
            available = np.asarray(self.axis_values(name), dtype=float)
            if len(available) == 0:
                raise GridPointNotFoundError(f"axis {name!r} has no values")
            i = int(np.argmin(np.abs(available - value)))
            snapped[name] = float(available[i])
            distances[name] = float(abs(available[i] - value))

        candidates = [
            iso
            for key, iso in self._sets_by_key.items()
            if all(
                key[self._selectable.index(name)] == value
                for name, value in snapped.items()
            )
        ]
        if len(candidates) == 1:
            iso = candidates[0]
        elif not candidates:
            raise GridPointNotFoundError(
                f"no isochrone at snapped coordinates {snapped} "
                f"(requested {requested}); available axes: {self.axes}"
            )
        else:
            # more than one candidate: unconstrained axes remain
            unpinned = [k for k in self._selectable if k not in requested]
            raise GridPointNotFoundError(
                f"snapped coordinates {snapped} match {len(candidates)} "
                f"isochrones; pin one of {unpinned}"
            )

        info = {
            "method": "nearest",
            "requested": dict(requested),
            "returned": dict(snapped),
            "distances": distances,
        }
        if any(d > 0 for d in distances.values()):
            warnings.warn(
                f"nearest grid point used: requested {requested}, "
                f"returned {snapped}, distances {distances}",
                NearestGridPointWarning,
                stacklevel=2,
            )
        return iso.with_selection_info(info)


def open_grid(
    path: str | os.PathLike, model: str | None = None
) -> IsochroneGrid:
    """Open a local grid from a file or directory of files.

    With ``model`` given (family only, ``"mist"``, or version-qualified,
    ``"mist/1.2"``), the corresponding backend reads every file it
    recognizes under ``path``; a stated release is validated against the
    files' own identity. Without ``model``, every registered backend
    sniffs the sources; exactly one must claim them
    (``AmbiguousFormatError`` otherwise, ``UnrecognizedFormatError`` if none).
    """
    from stellariso.models import parse_model_spec

    p = Path(path)
    if model is not None:
        family, release = parse_model_spec(model)
        grid = (
            IsochroneGrid.from_directory(family, p)
            if p.is_dir()
            else IsochroneGrid.from_paths(family, [p])
        )
        if release is not None and grid.identity.release != release:
            raise ValueError(
                f"model {model!r} does not match the data: the files state "
                f"release {grid.identity.release!r}"
            )
        return grid

    from stellariso.models import BACKENDS

    paths = (
        sorted(q for q in p.rglob("*") if q.is_file() and not q.name.startswith("."))
        if p.is_dir()
        else [p]
    )
    claiming = [
        name
        for name, backend in BACKENDS.items()
        if any(backend.recognize(q) for q in paths)
    ]
    if len(claiming) == 0:
        raise UnrecognizedFormatError(f"no backend recognizes {path}")
    if len(claiming) > 1:
        raise AmbiguousFormatError(
            f"backends {claiming} all claim {path}; pass model= explicitly"
        )
    return IsochroneGrid.from_directory(claiming[0], p) if p.is_dir() else (
        IsochroneGrid.from_paths(claiming[0], paths)
    )
