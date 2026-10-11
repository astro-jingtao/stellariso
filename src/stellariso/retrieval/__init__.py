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
    from ..exceptions import SourceUnavailableError
    from ..models.mist.fetch import fetch_mist_subset, fetch_mist_tarball

    def _parsec_manual(**kwargs):
        raise SourceUnavailableError(
            "PARSEC isochrone tables have no scriptable official channel "
            "today: the CMD 3.9 form accepts scripted jobs but returns "
            "header-only results, and no CDS/Zenodo deposit exists (checked "
            "2026-10-11). Obtain the table manually through a browser "
            "(https://stev.oapd.inaf.it/cgi-bin/cmd), save it, and load it "
            "with construct('parsec', paths=[...]) or open_grid(path, "
            "model='parsec'). See docs/data-sources.md."
        )

    return {
        "mist": {
            "subset": fetch_mist_subset,
            "tarball": fetch_mist_tarball,
        },
        "parsec": {
            "manual": _parsec_manual,
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
