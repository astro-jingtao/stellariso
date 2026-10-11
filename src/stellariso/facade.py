"""The unified facade: model-specific grid objects and ``construct()``.

``UnifiedIso`` is the abstract face of a loaded model product: selection by
(age, composition) plus point queries ``get_<field>(M, log_age, feh)`` that
combine conservative grid selection with within-isochrone interpolation.
``MistIso`` is the MIST implementation; ``construct(model=...)`` builds the
right subclass.
"""

from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import Any, Iterable

from .exceptions import UnsupportedModelError
from .grid import IsochroneGrid
from .interp import InterpolationRecord
from .isochrone import IsochroneSet

__all__ = ["UnifiedIso", "MistIso", "construct"]


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
        initial_feh: float | None = None,
        interp: str = "linear",
        selection: str = "nearest",
    ) -> float:
        """One quantity at (initial mass, log10 age, [Fe/H]).

        ``selection`` picks the isochrone (``nearest`` warns and records any
        snapping; ``exact`` requires an available grid point);
        ``interp`` chooses the within-isochrone method (``linear`` or
        ``pchip``). The interpolation record of the last call is kept on
        ``self.last_record``.
        """
        value, record = self.get_detailed(
            field, mass, log_age, initial_feh, interp=interp, selection=selection
        )
        return value

    def get_detailed(
        self,
        field: str,
        mass: float,
        log_age: float | None = None,
        initial_feh: float | None = None,
        interp: str = "linear",
        selection: str = "nearest",
    ) -> tuple[float, InterpolationRecord]:
        coordinates = {}
        if log_age is not None:
            coordinates["log_age"] = log_age
        if initial_feh is not None:
            coordinates["initial_feh"] = initial_feh
        iso = self.get_isochrone(method=selection, **coordinates)
        values, record = iso.at(mass, fields=field, method=interp, record=True)
        self.last_record = record
        return float(values), record

    # -- convenience queries (shared implementation) --------------------------

    def get_logg(self, mass, log_age=None, initial_feh=None, **kw) -> float:
        return self.get(
            "log_surface_gravity", mass, log_age, initial_feh, **kw
        )

    def get_log_teff(self, mass, log_age=None, initial_feh=None, **kw) -> float:
        return self.get(
            "log_effective_temperature", mass, log_age, initial_feh, **kw
        )

    def get_log_luminosity(self, mass, log_age=None, initial_feh=None, **kw) -> float:
        return self.get("log_luminosity", mass, log_age, initial_feh, **kw)

    def get_log_radius(self, mass, log_age=None, initial_feh=None, **kw) -> float:
        return self.get("log_radius", mass, log_age, initial_feh, **kw)

    def get_current_mass(self, mass, log_age=None, initial_feh=None, **kw) -> float:
        return self.get("current_mass", mass, log_age, initial_feh, **kw)

    def get_phase(self, mass, log_age=None, initial_feh=None, **kw) -> str:
        """Unified stage at the given mass. Phases are discrete: the value is
        read from the bracketing nodes — their stage when they agree,
        ``unknown`` with a warning when the mass straddles a boundary."""
        import warnings as _w

        import numpy as np

        from .warnings import PhaseMappingWarning

        coordinates = {}
        if log_age is not None:
            coordinates["log_age"] = log_age
        if initial_feh is not None:
            coordinates["initial_feh"] = initial_feh
        iso = self.get_isochrone(method=kw.pop("selection", "nearest"), **coordinates)
        masses = np.asarray(iso.native["initial_mass"], dtype=float)
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
    def construct(
        cls,
        feh: float | None = None,
        log_ages: Iterable[float] | None = None,
        vvcrit: float = 0.4,
        afe: float = 0.0,
        paths=None,
        cache_dir: Path | None = None,
        fetch_missing: bool = True,
        session=None,
    ) -> "MistIso":
        """Load MIST isochrones, fetching them first when not cached.

        Either ``paths`` (local files/directories) or a subset request
        (``feh`` + ``log_ages``) must be given; the full published suite is
        fetched explicitly through ``stellariso.retrieval.fetch('mist',
        channel='tarball')`` rather than as a silent default.
        """
        from .models.mist.backend import read_mist
        from .models.mist.fetch import fetch_mist_subset

        if paths is not None:
            grid = IsochroneGrid.from_paths("mist", _as_path_list(paths))
            return cls(grid.sets)

        if feh is None or log_ages is None:
            raise ValueError(
                "construct needs either paths= (local files) or an explicit "
                "subset request (feh= and log_ages=); for the complete "
                "published suite use retrieval.fetch('mist', "
                "channel='tarball') first"
            )
        if not fetch_missing:
            raise ValueError("fetch_missing=False requires paths=")
        path, prov = fetch_mist_subset(
            feh=feh,
            log_ages=log_ages,
            vvcrit=vvcrit,
            afe=afe,
            cache_dir=cache_dir,
            session=session,
        )
        sets = read_mist(path, provenance=prov)
        return cls([sets])


def _as_path_list(paths) -> list:
    if isinstance(paths, (str, Path)):
        return [paths]
    return list(paths)


_REGISTRY = {"mist": MistIso}


def construct(model: str, **kwargs: Any) -> UnifiedIso:
    """Build the unified object for ``model`` (see the subclass ``construct``)."""
    try:
        cls = _REGISTRY[model.lower()]
    except KeyError:
        raise UnsupportedModelError(
            f"no unified class registered for model {model!r}; "
            f"registered: {sorted(_REGISTRY)}"
        ) from None
    return cls.construct(**kwargs)
