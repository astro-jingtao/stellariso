"""The database's derived-facts cache, keyed by file quick signatures.

Part classification re-derives, on every scan and build, each present
part's integrity evidence: its sha256, and — where conformance is
content-based — the facts a full read of the file yields (the PARSEC
isochrone block counts come from a decompressed line scan of the table
itself). That work is pure: the same bytes always yield the same
answers. The cache maps each file's quick signature — the
``"{path}_{size}_{mtime_ns}"`` key built from the path RELATIVE to the
database root — to those answers, so a file that has not changed since
its last classification is classified with one ``stat`` instead of a
full read. The quick signature covers the file's identity: any write
changes ``mtime_ns`` (and, for a content change, ``size``), so a served
answer belongs to exactly the bytes on disk now.

The cache is an accelerator, never an authority: the MANIFEST's recorded
sha256 stays what integrity is judged against and the family designs
stay what conformance is judged against. Deleting
``signature_cache.json`` is always safe — the next scan re-derives
everything and rebuilds it, and a bypassed scan (``cache=False`` on the
scan and build entry points) never consults it at all: every check is a
full read, the force-full-check mode.

Keys are relative to the database root, so moving (or renaming, or
symlinking) the database within one machine keeps the cache valid.
There is deliberately no cross-machine invalidation: an mtime-preserving
copy (``cp -a``, ``rsync -a``, ``tar``) leaves the keys usable on the
new machine while the content went unverified in transit, so after
migrating a database to another machine, delete
``signature_cache.json`` to force one full re-verify (a fresh rsync
transfer verifies content by checksum anyway).

Three modes serve the different callers:

- writable (default) — load, serve recorded answers, record computed
  ones, save when dirty; the mode of scans and builds;
- ``writable=False`` — load, serve, record in memory only, never write
  the file; the mode of dry-run planning ("touch nothing") and of the
  transfer scans;
- bypass (``root=None``) — serve nothing, record nothing: every
  question is answered by computing it directly. What ``cache=False``
  hands the classification layer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from stellariso.integrity import sha256_file

__all__ = ["SIGNATURE_CACHE_NAME", "SignatureCache"]

SIGNATURE_CACHE_NAME = "signature_cache.json"


class SignatureCache:
    """Derived per-file answers keyed by quick signature.

    The store file is ``<root>/signature_cache.json``; keys are built
    from paths relative to ``root`` (the root is canonicalized through
    ``os.path.realpath``, so every alias of the database produces the
    same keys). ``writable=False`` serves and records in memory but
    never saves; ``root=None`` is the bypass: answers are always
    computed directly, nothing is served or kept. A corrupt store file
    raises (a damaged accelerator is surfaced, never silently dropped).
    """

    def __init__(self, root: str | Path | None = None, *, writable: bool = True) -> None:
        """One database's quick-signature cache (or the bypass)."""
        self._bypass = root is None
        self._root = Path(os.path.realpath(str(root))) if root is not None else None
        self._writable = writable
        self._dirty = False
        self._data: dict[str, dict[str, Any]] = {}
        if not self._bypass:
            store = self._root / SIGNATURE_CACHE_NAME
            if store.exists():
                self._data = json.loads(store.read_text(encoding="utf-8"))

    def _key(self, path: str | Path) -> str:
        """The file's quick signature: ``relpath_{size}_{mtime_ns}``."""
        real = os.path.realpath(str(path))
        rel = os.path.relpath(real, self._root).replace(os.sep, "/")
        st = os.stat(real)
        return f"{rel}_{st.st_size}_{st.st_mtime_ns}"

    def _record(self, key: str, name: str, value: Any) -> None:
        self._data.setdefault(key, {})[name] = value
        if self._writable:
            self._dirty = True

    def sha256(self, path: str | Path) -> str:
        """The file's sha256 — the recorded answer when the quick
        signature hits; a miss reads and hashes the file and records
        the answer (the bypass always reads and hashes)."""
        if self._bypass:
            return sha256_file(path)
        key = self._key(path)
        entry = self._data.get(key)
        if entry is not None and "sha256" in entry:
            return entry["sha256"]
        digest = sha256_file(path)
        self._record(key, "sha256", digest)
        return digest

    def fact(self, path: str | Path, name: str, compute: Callable[[], Any]) -> Any:
        """One derived content fact (``compute()`` yields it) — served
        from the recorded answer when the quick signature hits,
        computed and recorded on a miss (the bypass always computes).

        A recorded ``None`` is an answer like any other (a fact that
        could not be derived is a fact); only an absent name is a miss.
        """
        if self._bypass:
            return compute()
        key = self._key(path)
        entry = self._data.get(key)
        if entry is not None and name in entry:
            return entry[name]
        value = compute()
        self._record(key, name, value)
        return value

    def remember(self, path: str | Path, digest: str) -> None:
        """Record a sha256 already computed elsewhere (the streaming
        hash of a fetch), so the file's first classification needs no
        read. A no-op on the bypass."""
        if self._bypass:
            return
        self._record(self._key(path), "sha256", digest)

    def save_if_dirty(self) -> None:
        """Persist recorded answers (atomically); a clean cache writes
        nothing, so a served-only or bypassed cache never creates the
        file."""
        if self._bypass or not self._writable or not self._dirty:
            return
        store = self._root / SIGNATURE_CACHE_NAME
        tmp = store.with_name(store.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, store)
        self._dirty = False
