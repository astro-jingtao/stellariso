"""Backend registry: the set of supported isochrone model families.

Each backend contributes a cheap ``recognize`` sniffer and a full ``read``
function. Core code (grid, unified, retrieval) dispatches through this
registry — no ``if model == "mist"`` branches anywhere else.
"""

from __future__ import annotations

from typing import Callable

from ..exceptions import UnsupportedModelError
from .mist.backend import read_mist, recognize_mist

__all__ = ["BACKENDS", "get_backend", "register_backend"]


class Backend:
    """One model family's entry in the registry."""

    def __init__(self, name: str, recognize: Callable, read: Callable):
        self.name = name
        self.recognize = recognize
        self.read = read


BACKENDS: dict[str, Backend] = {
    "mist": Backend(name="mist", recognize=recognize_mist, read=read_mist),
}


def get_backend(name: str) -> Backend:
    try:
        return BACKENDS[name.lower()]
    except KeyError:
        raise UnsupportedModelError(
            f"no backend registered for model {name!r}; "
            f"registered models: {sorted(BACKENDS)}"
        ) from None


def register_backend(backend: Backend) -> None:
    """Register a third-party backend (extension point for new models)."""
    BACKENDS[backend.name.lower()] = backend
