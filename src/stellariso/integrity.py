"""Integrity helpers: checksums for fetched and on-disk assets."""

from __future__ import annotations

import hashlib
from pathlib import Path

from stellariso.exceptions import DataIntegrityError
from stellariso.warnings import ChecksumUnavailableWarning

__all__ = ["sha256_file", "sha256_bytes", "verify_checksum", "download_file"]

_CHUNK = 1 << 20
_TIMEOUT_GET = 1800


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def download_file(url: str, target: Path, session) -> tuple[str, int]:
    """Stream one remote file to its target; return (sha256, size_bytes).

    The digest is computed over the bytes as they arrive, so callers
    record integrity without a second read. The file lands at its final
    name only after the transfer completes (``.part`` during).
    """
    digest = hashlib.sha256()
    tmp = target.with_suffix(target.suffix + ".part")
    with session.get(url, stream=True, timeout=_TIMEOUT_GET) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                fh.write(chunk)
                digest.update(chunk)
    tmp.replace(target)
    return digest.hexdigest(), target.stat().st_size


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def verify_checksum(path: str | Path, expected: str | None) -> str:
    """Verify ``path`` against ``expected`` (hex sha256).

    Returns the file's actual checksum. A mismatch raises
    :class:`DataIntegrityError`; a missing expectation returns the actual
    checksum unchanged (callers decide whether to warn — upstreams that
    publish no checksums are recorded, never silently trusted).
    """
    actual = sha256_file(path)
    if expected is not None and actual.lower() != expected.lower():
        raise DataIntegrityError(
            f"{path}: sha256 {actual} does not match expected {expected}"
        )
    return actual
