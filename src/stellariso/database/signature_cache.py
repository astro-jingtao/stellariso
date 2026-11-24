"""The database's derived-facts cache, keyed by file quick signatures.

Part classification re-derives, on every scan and build, each present
part's integrity evidence: its sha256, and — where conformance is
content-based — the facts a full read of the file yields (the PARSEC
isochrone block counts come from a decompressed line scan of the table
itself). That work is pure: the same bytes always yield the same
answers. The cache maps each file's quick signature — the
``"{path}_{size}_{mtime_ns}"`` key of ``file_quick_signature``, built
from the path RELATIVE to the database root — to those answers, so a
file that has not changed since its last classification is classified
with one ``stat`` instead of a full read. The quick signature covers
the file's identity: any write changes ``mtime_ns`` (and, for a
content change, ``size``), so a served answer belongs to exactly the
bytes on disk now.

Storage is ``file_quick_signature``'s own :class:`SignatureStore` (the
``file_quick_signature`` package, a declared runtime dependency): it
owns the JSON persistence, the key grammar, and the
absolute-to-relative path keying. Each key's payload is this module's
own fact dictionary — ``{"sha256": ..., "blocks": ...}`` — whose
member names are the classification layer's fact names.

The cache is an accelerator, never an authority: the MANIFEST's recorded
sha256 stays what integrity is judged against and the family designs
stay what conformance is judged against. Deleting
``signature_cache.json`` is always safe — the next scan re-derives
everything and rebuilds it, and a bypassed scan (``cache=False`` on the
scan and build entry points, which classify with no cache at all)
never consults it: every check is a full read, the force-full-check
mode.

Keys are relative to the database root, so moving (or renaming, or
symlinking) the database within one machine keeps the cache valid.
There is deliberately no cross-machine invalidation: an mtime-preserving
copy (``cp -a``, ``rsync -a``, ``tar``) leaves the keys usable on the
new machine while the content went unverified in transit, so after
migrating a database to another machine, delete
``signature_cache.json`` to force one full re-verify (a fresh rsync
transfer verifies content by checksum anyway).

Two modes serve the different callers: writable (the default) —
load, serve recorded answers, record computed ones, save when dirty;
the mode of scans and builds. ``writable=False`` — load, serve,
record in memory only, never write the file; the mode of dry-run
planning ("touch nothing") and of the transfer scans.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from file_quick_signature.remapper import AbsoluteToRelativeRemapper
from file_quick_signature.store import SignatureStore

from stellariso.integrity import sha256_file

__all__ = ["SIGNATURE_CACHE_NAME", "SignatureCache"]

SIGNATURE_CACHE_NAME = "signature_cache.json"


class SignatureCache:
    """Derived per-file answers keyed by quick signature.

    The store file is ``<root>/signature_cache.json``, held by a
    ``file_quick_signature`` :class:`SignatureStore` whose keys are built
    from paths relative to ``root`` (the root is canonicalized the same
    way ``file_quick_signature`` canonicalizes files, so every alias of
    the database produces the same keys). Each key's payload is the
    fact dictionary of the classification layer. ``writable=False``
    serves and records in memory but never saves. A corrupt store file
    raises (a damaged accelerator is surfaced, never silently dropped).
    """

    def __init__(self, root: str | Path, *, writable: bool = True) -> None:
        """One database's quick-signature cache (a derived accelerator)."""
        self._root = Path(root)
        self._remapper = AbsoluteToRelativeRemapper(
            os.path.realpath(str(self._root))
        )
        self._store = SignatureStore(
            json_path=str(self._root / SIGNATURE_CACHE_NAME),
            file_remappers=self._remapper,
        ).load()
        self._writable = writable
        self._dirty = False

    def _record(self, key: str, name: str, value: Any) -> None:
        # Recorded in memory in every mode (a read-only scan still serves
        # its own computed answers afterwards); persisted only when
        # writable, at save_if_dirty.
        entry = self._store.data.get(key)
        if entry is None:
            entry = {}
            self._store.data[key] = entry
        entry[name] = value
        if self._writable:
            self._dirty = True

    def sha256(self, path: str | Path) -> str:
        """The file's sha256 — the recorded answer when the quick
        signature hits; a miss reads and hashes the file and records
        the answer."""
        key = self._store.signature(str(path))
        entry = self._store.data.get(key)
        if entry is not None and "sha256" in entry:
            return entry["sha256"]
        digest = sha256_file(path)
        self._record(key, "sha256", digest)
        return digest

    def fact(self, path: str | Path, name: str, compute: Callable[[], Any]) -> Any:
        """One derived content fact (``compute()`` yields it) — served
        from the recorded answer when the quick signature hits,
        computed and recorded on a miss.

        A recorded ``None`` is an answer like any other (a fact that
        could not be derived is a fact); only an absent name is a miss.
        """
        key = self._store.signature(str(path))
        entry = self._store.data.get(key)
        if entry is not None and name in entry:
            return entry[name]
        value = compute()
        self._record(key, name, value)
        return value

    def remember(self, path: str | Path, digest: str) -> None:
        """Record a sha256 already computed elsewhere (the streaming
        hash of a fetch), so the file's first classification needs no
        read."""
        self._record(self._store.signature(str(path)), "sha256", digest)

    def save_if_dirty(self) -> None:
        """Persist recorded answers (atomically); a clean cache writes
        nothing, so a read-only scan never creates the file."""
        if self._writable and self._dirty:
            self._store.save()
            self._dirty = False
