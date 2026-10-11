"""Tests for the local database: build, open, portability, registration."""

from __future__ import annotations

import io
import json
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from stellariso.database import (
    Database,
    build_database,
    open_database,
    register_local_product,
)
from stellariso.exceptions import (
    DataIntegrityError,
    SourceUnavailableError,
)
from stellariso.grid import IsochroneGrid
from stellariso.integrity import sha256_bytes, sha256_file, verify_checksum

MIST_FIXTURE = (
    Path(__file__).parent / "data" / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
)

FAKE_CATALOG = {
    "family": "mist",
    "channel": "packages",
    "source_note": "test catalog; checksums computed on download",
    "releases": [
        {
            "release": "1.2",
            "products": [
                {
                    "label": "vvcrit0.4_full_isos",
                    "kind": "isochrones",
                    "physics": {"vvcrit": 0.4, "columns": "full"},
                    "filename": "MIST_v1.2_vvcrit0.4_full_isos.txz",
                    "url": "https://fake.example/MIST_v1.2_vvcrit0.4_full_isos.txz",
                    "format": "isochrones",
                },
                {
                    "label": "vvcrit0.0_full_isos",
                    "kind": "isochrones",
                    "physics": {"vvcrit": 0.0, "columns": "full"},
                    "filename": "MIST_v1.2_vvcrit0.0_full_isos.txz",
                    "url": "https://fake.example/MIST_v1.2_vvcrit0.0_full_isos.txz",
                    "format": "isochrones",
                },
            ],
        }
    ],
}


class FakeStreamResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._payload), chunk_size):
            yield self._payload[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeStreamSession:
    """Serves prebuilt tarball payloads for the database builder."""

    def __init__(self, mapping: dict[str, bytes]):
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url, stream=True, timeout=None):
        self.calls.append(url)
        return FakeStreamResponse(self.mapping[url])


def _tarball_with_iso(arcname: str = "MIST_v1.2_feh_m1.00_test.iso") -> bytes:
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        data = MIST_FIXTURE.read_bytes()
        info = tarfile.TarInfo(name=arcname)
        info.size = len(data)
        tf.addfile(info, BytesIO(data))
    return buf.getvalue()


@pytest.fixture()
def fake_env(monkeypatch, tmp_path):
    payload = _tarball_with_iso()
    mapping = {
        product["url"]: payload
        for product in FAKE_CATALOG["releases"][0]["products"]
    }
    session = FakeStreamSession(mapping)
    monkeypatch.setattr(
        "stellariso.database.catalog", lambda family: FAKE_CATALOG
    )
    monkeypatch.setattr("stellariso.database.backend_names", lambda: ("mist",))
    return session, tmp_path / "db"


class TestIntegrityHelpers:
    def test_sha256_roundtrip(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        assert sha256_file(p) == sha256_bytes(b"hello")

    def test_verify_checksum_mismatch_raises(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        with pytest.raises(DataIntegrityError, match="sha256"):
            verify_checksum(p, "00" * 32)

    def test_verify_checksum_none_expectation_passes(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        assert verify_checksum(p, None) == sha256_file(p)


class TestBuildDatabase:
    def test_build_downloads_extracts_and_records(self, fake_env):
        session, db_path = fake_env
        db = build_database(db_path, session=session)
        assert len(session.calls) == 2
        for label in ("vvcrit0.4_full_isos", "vvcrit0.0_full_isos"):
            product_dir = db_path / "mist" / "1.2" / label
            archive = product_dir / "MIST_v1.2_vvcrit{rot}_full_isos.txz".format(
                rot=label.split("_")[0].removeprefix("vvcrit")
            )
            assert archive.exists()
            manifest = json.loads(
                (product_dir / "MANIFEST.json").read_text(encoding="utf-8")
            )
            assert manifest["family"] == "mist"
            assert manifest["release"] == "1.2"
            assert manifest["sha256"] == sha256_file(archive)
            assert manifest["source_class"] == "official_origin"
            assert manifest["retrieved_at"]
            assert any(p.suffix == ".iso" for p in product_dir.rglob("*.iso"))
        # self-containment artifacts
        assert (db_path / "database.json").exists()
        assert (db_path / "README.md").exists()
        assert (db_path / "unified-parameters.md").exists()
        inventory = json.loads((db_path / "database.json").read_text(encoding="utf-8"))
        assert len(inventory["products"]) == 2
        readme = (db_path / "README.md").read_text(encoding="utf-8")
        assert "Choi" in readme  # citations recorded

    def test_rebuild_keeps_verified_products(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, session=session)
        n = len(session.calls)
        build_database(db_path, session=session)
        assert len(session.calls) == n  # nothing re-downloaded
        db = open_database(db_path)
        assert len(db.products) == 2

    def test_dry_run_touches_nothing(self, fake_env, capsys):
        session, db_path = fake_env
        result = build_database(db_path, session=session, dry_run=True)
        assert result is None
        assert not session.calls
        assert not db_path.exists()
        out = capsys.readouterr().out
        assert "vvcrit0.4_full_isos" in out

    def test_manual_family_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "stellariso.database.catalog",
            lambda family: {
                "family": family,
                "channel": "manual",
                "manual_note": "no packages",
                "releases": [],
            },
        )
        with pytest.raises(SourceUnavailableError, match="publishes no downloadable"):
            build_database(tmp_path / "db", models=["parsec"])


class TestOpenDatabase:
    def test_open_and_grid(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, session=session)
        db = open_database(db_path)
        assert len(db.products) == 2
        grid = db.grid("mist/1.2", label="vvcrit0.4_full_isos")
        assert isinstance(grid, IsochroneGrid)
        assert len(grid) > 0
        prov = db.provenance("mist/1.2", label="vvcrit0.4_full_isos")
        assert prov.data_sources[0].url.endswith(".txz")

    def test_unqualified_model_rejected(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, session=session)
        db = open_database(db_path)
        with pytest.raises(ValueError, match="version-qualified"):
            db.grid("mist")

    def test_ambiguous_products_require_label(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, session=session)
        db = open_database(db_path)
        with pytest.raises(ValueError, match="pin one"):
            db.grid("mist/1.2")

    def test_missing_release_lists_present_products(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, session=session)
        db = open_database(db_path)
        with pytest.raises(SourceUnavailableError, match="holds no"):
            db.grid("mist/2.5", label="vvcrit0.4_full_isos")

    def test_partial_copy_is_portable(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, session=session)
        partial = db_path.parent / "partial_db"
        (partial / "mist" / "1.2").mkdir(parents=True)
        # copy ONE product directory only
        import shutil

        shutil.copytree(
            db_path / "mist" / "1.2" / "vvcrit0.4_full_isos",
            partial / "mist" / "1.2" / "vvcrit0.4_full_isos",
        )
        db = open_database(partial)
        assert len(db.products) == 1
        assert db.grid("mist/1.2", label="vvcrit0.4_full_isos")

    def test_open_missing_directory_fails(self, tmp_path):
        with pytest.raises(NotADirectoryError, match="build_database"):
            open_database(tmp_path / "nope")


class TestRegisterLocalProduct:
    def test_register_manual_files(self, tmp_path):
        db_path = tmp_path / "db"
        db_path.mkdir()
        record = register_local_product(
            db_path,
            family="parsec",
            release="v1.2S+COLIBRI",
            label="manual_cmd_tables",
            files=[MIST_FIXTURE],  # any data file works for the mechanics
            note="obtained manually through the CMD web form on 2026-10-11",
        )
        assert record.manifest["source_class"] == "local_user_file"
        db = open_database(db_path)
        assert len(db.products) == 1
        assert db.products_for("parsec")
        inventory = json.loads((db_path / "database.json").read_text(encoding="utf-8"))
        assert inventory["products"][0]["family"] == "parsec"


class TestSafeExtract:
    def test_escaping_member_rejected(self, tmp_path):
        import stellariso.database as dbmod

        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            data = b"evil"
            info = tarfile.TarInfo(name="../evil.txt")
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:") as tf, pytest.raises(
            ValueError, match="escapes"
        ):
            dbmod._safe_extract(tf, tmp_path / "out")
