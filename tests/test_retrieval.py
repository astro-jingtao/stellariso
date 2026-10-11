"""Offline tests for the retrieval layer (network mocked)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from stellariso.exceptions import DataIntegrityError, SourceUnavailableError
from stellariso.models.mist.fetch import (
    FORM_URL,
    fetch_mist_subset,
    mist_subset_filename,
)
from stellariso.provenance import SourceClass, SourceStatus
from stellariso.retrieval import fetch
from stellariso.retrieval.cache import cache_root
from stellariso.retrieval.integrity import sha256_bytes, sha256_file, verify_checksum

FIXTURE = (
    Path(__file__).parent / "data" / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
)


class FakeResponse:
    def __init__(self, content: bytes, text: str | None = None, status_code: int = 200):
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", "replace")
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Serves the interp-form flow from fixture bytes; records requests."""

    def __init__(self, iso_payload: bytes):
        form_html = (
            "<html>Your output is ready: "
            '<a href="output/MIST_iso_deadbeef.zip">MIST_iso_deadbeef.zip</a>'
            "</html>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("MIST_iso_deadbeef.iso", iso_payload)
        self.zip_bytes = buf.getvalue()
        self.form_html = form_html
        self.calls = []

    def post(self, url, data=None, timeout=None, **kw):
        self.calls.append(("POST", url, dict(data)))
        assert url == FORM_URL
        return FakeResponse(b"", text=self.form_html)

    def get(self, url, timeout=None, **kw):
        self.calls.append(("GET", url, None))
        assert url.endswith("output/MIST_iso_deadbeef.zip")
        return FakeResponse(self.zip_bytes)


@pytest.fixture()
def iso_payload() -> bytes:
    return FIXTURE.read_bytes()


class TestFetchSubset:
    def test_end_to_end_offline(self, tmp_path, iso_payload):
        session = FakeSession(iso_payload)
        path, prov = fetch_mist_subset(
            feh=-1.0, log_ages=[9.0, 10.0], cache_dir=tmp_path, session=session
        )
        assert path.exists()
        assert path.read_bytes() == iso_payload
        # deterministic filename
        assert path.name == mist_subset_filename(-1.0, [9.0, 10.0], 0.4, 0.0, "1.2")
        # registry written with checksum
        reg = json.loads((tmp_path / "registry.json").read_text())
        entry = reg["assets"][path.name]
        assert entry["sha256"] == sha256_bytes(iso_payload)
        assert entry["source"]["source_class"] == "official_origin"
        # provenance carries source + asset
        assert prov.data_sources[0].source_class is SourceClass.OFFICIAL_ORIGIN
        assert prov.assets[0].checksum == entry["sha256"]
        # the fetched file round-trips through the reader
        from stellariso.models.mist.backend import read_mist

        s = read_mist(path)
        assert len(s) == 2

    def test_cached_file_reused(self, tmp_path, iso_payload):
        session = FakeSession(iso_payload)
        path1, _ = fetch_mist_subset(
            feh=-1.0, log_ages=[9.0], cache_dir=tmp_path, session=session
        )
        n_calls = len(session.calls)
        # second call must not hit the network
        path2, prov2 = fetch_mist_subset(
            feh=-1.0, log_ages=[9.0], cache_dir=tmp_path, session=session
        )
        assert path1 == path2
        assert len(session.calls) == n_calls
        assert prov2.assets[0].checksum == sha256_bytes(iso_payload)

    def test_corrupted_cache_refetched(self, tmp_path, iso_payload):
        session = FakeSession(iso_payload)
        path, _ = fetch_mist_subset(
            feh=-1.0, log_ages=[9.0], cache_dir=tmp_path, session=session
        )
        path.write_bytes(iso_payload[:-100] + b"x" * 100)
        calls_before = len(session.calls)
        path2, _ = fetch_mist_subset(
            feh=-1.0, log_ages=[9.0], cache_dir=tmp_path, session=session
        )
        assert len(session.calls) > calls_before
        assert path2.read_bytes() == iso_payload

    def test_missing_zip_link_raises(self, tmp_path, iso_payload):
        class BrokenSession(FakeSession):
            def post(self, url, data=None, timeout=None, **kw):
                return FakeResponse(b"", text="<html>error page</html>")

        with pytest.raises(SourceUnavailableError, match="no result zip"):
            fetch_mist_subset(
                feh=-1.0, log_ages=[9.0], cache_dir=tmp_path, session=BrokenSession(iso_payload)
            )

    def test_empty_ages_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            fetch_mist_subset(feh=0.0, log_ages=[], cache_dir=tmp_path)


class TestFetchDispatch:
    def test_dispatch_to_mist_subset(self, tmp_path, iso_payload):
        session = FakeSession(iso_payload)
        path, _ = fetch(
            "mist", channel="subset", feh=0.0, log_ages=[9.0], cache_dir=tmp_path, session=session
        )
        assert path.exists()

    def test_unknown_model(self):
        from stellariso.exceptions import UnsupportedModelError

        with pytest.raises(UnsupportedModelError):
            fetch("nonexistent", channel="subset")

    def test_unknown_channel(self):
        with pytest.raises(ValueError, match="channel"):
            fetch("mist", channel="ftp")


class TestIntegrity:
    def test_verify_ok(self, tmp_path, iso_payload):
        p = tmp_path / "x.iso"
        p.write_bytes(iso_payload)
        assert verify_checksum(p, sha256_bytes(iso_payload)) == sha256_file(p)

    def test_verify_mismatch(self, tmp_path, iso_payload):
        p = tmp_path / "x.iso"
        p.write_bytes(iso_payload)
        with pytest.raises(DataIntegrityError, match="does not match"):
            verify_checksum(p, "0" * 64)

    def test_verify_none_expectation(self, tmp_path, iso_payload):
        p = tmp_path / "x.iso"
        p.write_bytes(iso_payload)
        assert verify_checksum(p, None) == sha256_bytes(iso_payload)


class TestCacheLayout:
    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STELLARISO_DATA", str(tmp_path))
        assert cache_root() == tmp_path

    def test_default_layout(self, monkeypatch):
        monkeypatch.delenv("STELLARISO_DATA", raising=False)
        assert cache_root().name == ".stellariso"
