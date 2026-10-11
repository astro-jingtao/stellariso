"""Data retrieval entry points.

``fetch`` dispatches to a model backend's acquisition functions. Official
sources are the default and, for now, the only automated channel; the PARSEC
CMD form cannot currently be scripted (see docs/data-sources.md) and PARSEC
files enter through ``local_user_file`` provenance instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["fetch"]


def _channels() -> dict:
    # imported lazily: model fetch modules import retrieval.cache, and a
    # module-level import here would make the two packages circular
    from ..models.mist.fetch import fetch_mist_subset, fetch_mist_tarball

    return {
        "mist": {
            "subset": fetch_mist_subset,
            "tarball": fetch_mist_tarball,
        },
    }


def fetch(model: str, channel: str = "subset", **kwargs: Any) -> tuple[Path, Any]:
    """Fetch data for ``model`` through ``channel`` and return
    ``(path, provenance)``."""
    from ..exceptions import UnsupportedModelError

    channels = _channels()
    try:
        model_channels = channels[model.lower()]
    except KeyError:
        raise UnsupportedModelError(
            f"no fetch channels registered for model {model!r}; "
            f"registered: {sorted(channels)}"
        ) from None
    try:
        fn = model_channels[channel]
    except KeyError:
        raise ValueError(
            f"model {model!r} has no channel {channel!r}; "
            f"available: {sorted(model_channels)}"
        ) from None
    return fn(**kwargs)
