"""Backend registry: the set of supported isochrone model families.

Each backend contributes a cheap ``recognize`` sniffer and a full ``read``
function, plus a release ``catalog`` (the published packages a local
database is built from). Core code dispatches through this registry — no
``if model == "mist"`` branches anywhere else.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from stellariso.exceptions import SourceUnavailableError, UnsupportedModelError
from stellariso.models.mist.backend import read_mist, recognize_mist
from stellariso.models.parsec.backend import read_parsec, recognize_parsec

__all__ = ["BACKENDS", "get_backend", "register_backend", "catalog", "parse_model_spec"]


class Backend:
    """One model family's entry in the registry."""

    def __init__(self, name: str, recognize: Callable, read: Callable):
        self.name = name
        self.recognize = recognize
        self.read = read


BACKENDS: dict[str, Backend] = {
    "mist": Backend(name="mist", recognize=recognize_mist, read=read_mist),
    "parsec": Backend(
        name="parsec", recognize=recognize_parsec, read=read_parsec
    ),
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


def catalog(family: str) -> dict:
    """The family's release catalog: every published package to acquire.

    The catalog is data (``models/<family>/catalog.json``) so the database
    builder stays model-agnostic. Entries state the exact URL, filename,
    product kind, and physics configuration of each official package.
    """
    get_backend(family)  # validates the family name
    path = Path(__file__).parent / family.lower() / "catalog.json"
    if not path.exists():
        raise SourceUnavailableError(
            f"model family {family!r} declares no release catalog"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def parse_model_spec(model: str) -> tuple[str, str | None]:
    """Split ``"mist/1.2"`` into ``("mist", "1.2")``.

    A bare family (``"mist"``) yields ``(family, None)`` — accepted only
    where autodetection is possible (open_grid sniffing); APIs that must
    know the release reject ``None``.
    """
    parts = [p.strip() for p in model.split("/")]
    if len(parts) == 1 and parts[0]:
        return parts[0].lower(), None
    if len(parts) == 2 and all(parts):
        return parts[0].lower(), parts[1]
    raise ValueError(
        f"model must be '<family>' or '<family>/<release>', "
        f"e.g. 'mist/1.2'; got {model!r}"
    )
