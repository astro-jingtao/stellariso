"""The unified facade: model-specific grid objects and ``construct()``.

``UnifiedIso`` is the abstract face of a loaded model product: selection by
(age, composition) plus point queries ``get_<field>(M, log_age, feh)`` that
combine conservative grid selection with within-isochrone interpolation.
``construct(model="mist/1.2")`` builds the right subclass from local paths
or from a built database.
"""

from __future__ import annotations

from abc import ABC
from pathlib import Path

from stellariso.database import Database
from stellariso.exceptions import UnsupportedModelError
from stellariso.grid import IsochroneGrid
from stellariso.interp import InterpolationRecord
from stellariso.isochrone import IsochroneSet

__all__ = ["UnifiedIso", "MistIso", "ParsecIso", "construct"]


class UnifiedIso(IsochroneGrid, ABC):
    """Abstract unified interface over one model's isochrone product.

    Concrete subclasses declare ``model_name`` and inherit the generic
    implementation; the per-model behavior lives in the backend the grid was
    built from.
    """

    model_name: str = ""

    def __init__(self, sets: Iterable[IsochroneSet]):
        super().__init__(sets)
        self.last_record: InterpolationRecord | None = None

    # -- point queries --------------------------------------------------------

    def get(
        self,
        field: str,
        mass: float,
        log_age: float | None = None,
        interp: str = "linear",
        selection: str = "nearest",
        **coordinates,
    ) -> float:
        """One quantity at (initial mass, grid coordinates).

        ``log_age`` and any backend coordinate (MIST: ``initial_feh``,
        ``alpha_fe``, ``initial_rotation``; PARSEC: ``initial_z``) select the
        isochrone — ``nearest`` warns and records any snapping, ``exact``
        requires an available grid point. ``interp`` chooses the
        within-isochrone method (``linear`` or ``pchip``). The interpolation
        record of the last call is kept on ``self.last_record``.
        """
        value, record = self.get_detailed(
            field, mass, log_age, interp=interp, selection=selection, **coordinates
        )
        return value

    def get_detailed(
        self,
        field: str,
        mass: float,
        log_age: float | None = None,
        interp: str = "linear",
        selection: str = "nearest",
        **coordinates,
    ) -> tuple[float, InterpolationRecord]:
        coords = dict(coordinates)
        if log_age is not None:
            coords["log_age"] = log_age
        iso = self.get_isochrone(method=selection, **coords)
        values, record = iso.at(mass, fields=field, method=interp, record=True)
        self.last_record = record
        return float(values), record

    # -- convenience queries (shared implementation) --------------------------

    def get_logg(self, mass, log_age=None, **kw) -> float:
        return self.get("log_surface_gravity", mass, log_age=log_age, **kw)

    def get_log_teff(self, mass, log_age=None, **kw) -> float:
        return self.get(
            "log_effective_temperature", mass, log_age=log_age, **kw
        )

    def get_log_luminosity(self, mass, log_age=None, **kw) -> float:
        return self.get("log_luminosity", mass, log_age=log_age, **kw)

    def get_log_radius(self, mass, log_age=None, **kw) -> float:
        return self.get("log_radius", mass, log_age=log_age, **kw)

    def get_current_mass(self, mass, log_age=None, **kw) -> float:
        return self.get("current_mass", mass, log_age=log_age, **kw)

    def get_phase(self, mass, log_age=None, **kw) -> str:
        """Unified stage at the given mass. Phases are discrete: the value is
        read from the bracketing nodes — their stage when they agree,
        ``unknown`` with a warning when the mass straddles a boundary."""
        import warnings as _w

        import numpy as np

        from stellariso.warnings import PhaseMappingWarning

        coordinates = dict(kw)
        selection = coordinates.pop("selection", "nearest")
        if log_age is not None:
            coordinates["log_age"] = log_age
        iso = self.get_isochrone(method=selection, **coordinates)
        masses = np.asarray(iso.unified["initial_mass"], dtype=float)
        stages = iso.unified["phase"]
        i = int(np.searchsorted(masses, mass, side="right")) - 1
        i = min(max(i, 0), len(masses) - 1)
        if i < len(masses) - 1 and masses[i] != mass and i + 1 < len(masses):
            left, right = stages[i], stages[i + 1]
            if left != right:
                _w.warn(
                    f"mass {mass} straddles a phase boundary "
                    f"({left} / {right}); returning 'unknown'",
                    PhaseMappingWarning,
                    stacklevel=2,
                )
                return "unknown"
        return str(stages[i])

    def describe(self) -> str:
        lines = [
            f"{type(self).__name__}: {self.identity.label}",
            f"product: {self.identity.product}",
            f"isochrones: {len(self)}",
        ]
        for name, values in self.axes.items():
            if values:
                lines.append(f"axis {name}: {values if len(values) <= 8 else f'{values[0]}..{values[-1]} ({len(values)} values)'}")
        return "\n".join(lines)


class MistIso(UnifiedIso):
    """MIST theoretical isochrones under the unified interface."""

    model_name = "mist"

    @classmethod
    def construct(cls, paths=None) -> "MistIso":
        """Load MIST isochrones from local files or directories.

        MIST data is not fetched on demand: build a local database with
        ``stellariso.build_database(database=...)`` (the complete published
        tarballs) and load from it, or pass ``paths`` of files you hold.
        """
        if paths is None:
            raise ValueError(
                "construct('mist') requires paths= of local files; MIST data "
                "is never fetched on demand — build a database first with "
                "stellariso.build_database(database=...)"
            )
        grid = IsochroneGrid.from_paths("mist", _as_path_list(paths))
        return cls(grid.sets)


class ParsecIso(UnifiedIso):
    """PARSEC/PADova CMD isochrone tables under the unified interface."""

    model_name = "parsec"

    @classmethod
    def construct(cls, paths=None) -> "ParsecIso":
        """Load CMD isochrone tables from local files.

        PARSEC publishes no downloadable packages: isochrone tables are
        obtained through the CMD web form by hand (see
        ``docs/data-sources.md``) and registered into a database with
        ``register_local_product``, or passed here directly.
        """
        if paths is None:
            raise ValueError(
                "construct('parsec/<release>') requires paths= to locally "
                "obtained files; PARSEC has no download channel — see "
                "docs/data-sources.md for the manual procedure"
            )
        grid = IsochroneGrid.from_paths("parsec", _as_path_list(paths))
        return cls(grid.sets)


def _as_path_list(paths) -> list:
    if isinstance(paths, (str, Path)):
        return [paths]
    return list(paths)


_REGISTRY = {"mist": MistIso, "parsec": ParsecIso}


def construct(
    model: str,
    paths=None,
    database=None,
    label: str | None = None,
) -> UnifiedIso:
    """Build the unified point-query facade for one model product.

    ``model`` is version-qualified: ``"mist/1.2"``, ``"parsec/v1.2S+COLIBRI
    PR16"``. The release part is validated against what the files state
    about themselves — a mismatch fails loudly.

    Data comes either from ``paths`` (files or directories you hold) or
    from a ``database`` built with ``stellariso.build_database`` (use
    ``label`` to pick one product when a release publishes several, e.g.
    rotation sets); never from the network.
    """
    from stellariso.models import parse_model_spec

    family, release = parse_model_spec(model)
    if release is None:
        raise ValueError(
            f"model must be version-qualified, e.g. 'mist/1.2'; got {model!r}"
        )
    try:
        cls = _REGISTRY[family]
    except KeyError:
        raise UnsupportedModelError(
            f"no unified class registered for model {model!r}; "
            f"registered families: {sorted(_REGISTRY)}"
        ) from None

    if database is not None:
        if paths is not None:
            raise ValueError("pass either paths= or database=, not both")
        from stellariso.database import open_database

        db = database if isinstance(database, Database) else open_database(database)
        grid = db.grid(model, label=label)
        obj = cls(grid.sets)
    else:
        obj = cls.construct(paths=paths)

    if obj.identity.release != release:
        raise ValueError(
            f"model {model!r} does not match the data: the files state "
            f"release {obj.identity.release!r}"
        )
    return obj
