"""Tests for the database's quick-signature cache.

The cache is the scan's accelerator and nothing else, so the tests pin
the contract: a hit serves the recorded answer without reading the
file, any write is a new signature (nothing is served stale), a
non-writing cache never creates the store file, and the keys are
POSIX-relative on every OS (a store written under one OS reads back
under another). The bypass (every check a full read, no store file) is
pinned at the scan entry.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from stellariso.database.scan import scan_database
import stellariso.database.signature_cache as sig_mod
from stellariso.database.signature_cache import SIGNATURE_CACHE_NAME, SignatureCache
from stellariso.integrity import sha256_file
from stellariso.models.mist.design import MistAdapter


def _forge_recorded_sha(root: Path, digest: str) -> None:
    """Overwrite the store's single entry with a wrong sha256, keeping
    the key (the file's current quick signature) intact."""
    store_path = root / SIGNATURE_CACHE_NAME
    store = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(store) == 1
    for entry in store.values():
        entry["sha256"] = digest
    store_path.write_text(json.dumps(store), encoding="utf-8")


def _mist_product(root: Path) -> Path:
    """One complete MIST product (archive + MANIFEST) under ``root``."""
    design = next(
        d
        for d in MistAdapter().designs()
        if d.collection == "1.2" and d.label == "vvcrit0.4_full_isos"
    )
    directory = root / design.relative_dir
    directory.mkdir(parents=True)
    archive = directory / design.parts[0].filename
    archive.write_bytes(b"payload")
    (directory / "MANIFEST.json").write_text(
        json.dumps(
            {
                "schema": "stellariso-manifest/2",
                "family": "mist",
                "parts": {
                    "archive": {"file": archive.name, "sha256": sha256_file(archive)}
                },
            }
        ),
        encoding="utf-8",
    )
    return archive


class TestSha256:
    def test_miss_computes_and_persists(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        cache = SignatureCache(tmp_path)
        assert cache.sha256(f) == sha256_file(f)
        cache.save_if_dirty()
        assert json.loads((tmp_path / SIGNATURE_CACHE_NAME).read_text(encoding="utf-8"))

    def test_hit_serves_the_recorded_answer_without_reading(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        cache = SignatureCache(tmp_path)
        cache.sha256(f)
        cache.save_if_dirty()
        # a fresh instance, after forging a wrong answer under the
        # file's CURRENT signature: served verbatim — the hit path
        # never reads the file
        _forge_recorded_sha(tmp_path, "f" * 64)
        assert SignatureCache(tmp_path).sha256(f) == "f" * 64

    def test_any_write_is_a_new_signature(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"one")
        cache = SignatureCache(tmp_path)
        first = cache.sha256(f)
        f.write_bytes(b"two bytes")  # size changes
        assert cache.sha256(f) == sha256_file(f)
        time.sleep(0.01)  # mtime granularity: let the clock tick
        f.write_bytes(b"tr2")  # same size, new mtime
        assert cache.sha256(f) == sha256_file(f)
        assert first != cache.sha256(f)

    def test_remember_serves_without_reading(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        cache = SignatureCache(tmp_path)
        cache.remember(f, "0" * 64)  # a digest from elsewhere (e.g. a fetch)
        assert cache.sha256(f) == "0" * 64  # served, not re-hashed

    def test_deleting_the_store_forces_full_reverify(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        cache = SignatureCache(tmp_path)
        cache.sha256(f)
        cache.save_if_dirty()
        _forge_recorded_sha(tmp_path, "f" * 64)
        (tmp_path / SIGNATURE_CACHE_NAME).unlink()
        assert SignatureCache(tmp_path).sha256(f) == sha256_file(f)


class TestFact:
    def test_computed_once_then_served(self, tmp_path: Path):
        f = tmp_path / "table.dat"
        f.write_bytes(b"# Zini\n" * 3)
        calls = []
        cache = SignatureCache(tmp_path)

        def compute() -> int:
            calls.append(1)
            return 3

        assert cache.fact(f, "blocks", compute) == 3
        assert cache.fact(f, "blocks", compute) == 3
        assert len(calls) == 1

    def test_none_is_a_recorded_answer_not_a_miss(self, tmp_path: Path):
        f = tmp_path / "table.dat"
        f.write_bytes(b"")
        calls = []
        cache = SignatureCache(tmp_path)

        def compute():
            calls.append(1)
            return  # e.g. an unreadable table

        assert cache.fact(f, "blocks", compute) is None
        assert cache.fact(f, "blocks", compute) is None
        assert len(calls) == 1


class TestModes:
    def test_writable_false_records_in_memory_never_writes(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        cache = SignatureCache(tmp_path, writable=False)
        assert cache.sha256(f) == sha256_file(f)  # computed on the miss
        cache.save_if_dirty()
        assert not (tmp_path / SIGNATURE_CACHE_NAME).exists()
        assert cache.sha256(f) == sha256_file(f)  # in-memory answer serves

    def test_root_aliases_produce_the_same_keys(self, tmp_path: Path):
        real = tmp_path / "db"
        real.mkdir()
        (real / "data.bin").write_bytes(b"payload")
        alias = tmp_path / "link"
        alias.symlink_to(real, target_is_directory=True)
        via_alias = alias / "data.bin"

        cache = SignatureCache(real)
        cache.sha256(real / "data.bin")
        cache.save_if_dirty()

        other = SignatureCache(alias)
        assert other.sha256(via_alias) == sha256_file(via_alias)
        other.save_if_dirty()
        store = json.loads((real / SIGNATURE_CACHE_NAME).read_text(encoding="utf-8"))
        assert len(store) == 1  # the alias resolved to the same key

    def test_corrupt_store_raises(self, tmp_path: Path):
        (tmp_path / SIGNATURE_CACHE_NAME).write_text("{not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            SignatureCache(tmp_path)


class TestCrossOsKeys:
    """The store's cross-OS contract: keys are POSIX-relative on every
    OS, so a store written under one OS reads back under another."""

    def test_windows_flavor_remap_answers_posix_keys(self, tmp_path: Path):
        # the windows flavor (detected textually from the base, on any
        # host) must answer the same "/"-joined relative component the
        # local flavor does, or a cache written under one OS could never
        # read back under another
        windows = sig_mod._PosixRelativeRemapper(r"E:\db")
        assert (
            windows.remap(r"E:\db\mist\1.2\vvcrit0.4_full_isos\a.iso")
            == "mist/1.2/vvcrit0.4_full_isos/a.iso"
        )
        assert windows.remap(r"E:/db\mist") == "mist"  # "/" reads as one too
        root = tmp_path.resolve()
        local = sig_mod._PosixRelativeRemapper(str(root))
        assert local.remap(str(root / "mist" / "1.2")) == "mist/1.2"

    def test_cache_written_under_windows_reads_back_here(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # end-to-end read-back: entries keyed through the windows
        # pipeline (same relative component, same size and mtime as the
        # local files) hit on this reader with one stat per file
        _mist_product(tmp_path)
        windows = sig_mod._PosixRelativeRemapper(r"E:\db")
        entries = {}
        for path in sorted(tmp_path.rglob("*")):
            if not path.is_file() or path.name == SIGNATURE_CACHE_NAME:
                continue
            st = path.stat()
            win_path = "\\".join((r"E:\db", *path.relative_to(tmp_path).parts))
            rel = windows.remap(win_path)
            entries[f"{rel}_{st.st_size}_{st.st_mtime_ns}"] = {
                "sha256": sha256_file(path)
            }
        (tmp_path / SIGNATURE_CACHE_NAME).write_text(
            json.dumps(entries), encoding="utf-8"
        )
        reads = {"n": 0}
        real = sig_mod.sha256_file

        def _counting(path, *args, **kwargs):
            reads["n"] += 1
            return real(path, *args, **kwargs)

        monkeypatch.setattr(sig_mod, "sha256_file", _counting)
        report = scan_database(tmp_path)
        assert reads["n"] == 0
        assert (
            report.families["mist"].products["1.2/vvcrit0.4_full_isos"].state
            == "complete"
        )


class TestScanIntegration:
    def test_cache_on_and_off_agree_and_catch_a_tamper(self, tmp_path: Path):
        archive = _mist_product(tmp_path)
        warmed = scan_database(tmp_path)  # default: cache on, store written
        assert (tmp_path / SIGNATURE_CACHE_NAME).exists()
        bypassed = scan_database(tmp_path, cache=False)
        assert (
            warmed.families["mist"].products["1.2/vvcrit0.4_full_isos"].state
            == bypassed.families["mist"].products["1.2/vvcrit0.4_full_isos"].state
            == "complete"
        )

        # a same-size rewrite changes only the mtime: the warm cache must
        # not serve the old answer
        archive.write_bytes(b"payloaX")
        for kwargs in ({}, {"cache": False}):
            scan = scan_database(tmp_path, **kwargs).families["mist"].products[
                "1.2/vvcrit0.4_full_isos"
            ]
            assert scan.state == "incomplete"
            assert scan.needs_review

    def test_bypass_scan_writes_no_store_file(self, tmp_path: Path):
        _mist_product(tmp_path)
        scan_database(tmp_path, cache=False)
        assert not (tmp_path / SIGNATURE_CACHE_NAME).exists()
