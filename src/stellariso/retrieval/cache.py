"""Data cache: where fetched isochrone products live on disk.

The cache follows the FSPS ``SPS_HOME`` pattern: one root directory,
overridable through the environment (``STELLARISO_DATA``), holding the raw
upstream files. It doubles as the offline backup — once fetched, a file with
a matching checksum is never re-fetched — and every file is recorded in a
per-product JSON registry carrying source, checksum, and request parameters.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = ["cache_root", "product_dir", "registry_path", "load_registry", "update_registry"]


def cache_root() -> Path:
    """Root of the stellariso data cache (``$STELLARISO_DATA`` or
    ``~/.stellariso``)."""
    env = os.environ.get("STELLARISO_DATA")
    return Path(env).expanduser() if env else Path.home() / ".stellariso"


def product_dir(model: str, release: str, physics: str | None = None) -> Path:
    """Directory for one product, e.g. ``<root>/mist/v1.2/vvcrit0.4``."""
    parts = [cache_root(), model, release]
    if physics:
        parts.append(physics)
    d = Path(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path(model: str, release: str, physics: str | None = None) -> Path:
    return product_dir(model, release, physics) / "registry.json"


def load_registry(model: str, release: str, physics: str | None = None) -> dict:
    p = registry_path(model, release, physics)
    if not p.exists():
        return {"assets": {}}
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def update_registry(
    model: str,
    release: str,
    physics: str | None,
    mutator,
) -> dict:
    """Read-modify-write the product registry; ``mutator(registry)`` edits it."""
    reg = load_registry(model, release, physics)
    mutator(reg)
    p = registry_path(model, release, physics)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=2, sort_keys=True)
    tmp.replace(p)
    return reg
