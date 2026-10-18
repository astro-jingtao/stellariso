"""Tests for the local database: build, open, portability, registration."""

from __future__ import annotations

import io
import json
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

import stellariso
from stellariso.database.build import build_database
from stellariso.database.core import Database, open_database, register_local_product
from stellariso.exceptions import (
    DataIntegrityError,
    SourceUnavailableError,
)
from stellariso.facade import MistIso, construct
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
        "stellariso.models.mist.design.load_catalog", lambda family: FAKE_CATALOG
    )
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
        db = build_database(db_path, models=["mist"], session=session)
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
            assert manifest["schema"] == "stellariso-manifest/2"
            assert manifest["family"] == "mist"
            assert manifest["release"] == "1.2"
            assert manifest["parts"]["archive"]["sha256"] == sha256_file(archive)
            assert manifest["parts"]["archive"]["file"] == archive.name
            assert manifest["source_class"] == "official_origin"
            assert manifest["parts"]["archive"]["retrieved_at"]
            assert manifest["extracted"] is True
            assert any(p.suffix == ".iso" for p in product_dir.rglob("*.iso"))
        # the archive itself always stays next to its extraction
        assert (db_path / "mist" / "1.2" / "vvcrit0.4_full_isos" / "MIST_v1.2_vvcrit0.4_full_isos.txz").exists()
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
        build_database(db_path, models=["mist"], session=session)
        n = len(session.calls)
        build_database(db_path, models=["mist"], session=session)
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
        assert "archive missing" in out

    def test_manual_family_fails_loudly(self, tmp_path):
        from stellariso.database.design import (
            DirectoryMatch,
            FamilyAdapter,
            PartDesign,
            PartVerdict,
            ProductDesign,
            register_adapter,
            unregister_adapter,
        )

        class ManualAdapter(FamilyAdapter):
            family = "manualsrc"

            def designs(self):
                return [
                    ProductDesign(
                        family="manualsrc",
                        collection="r",
                        release="r",
                        label="only",
                        kind="manual_files",
                        parts=(PartDesign("files", "data.iso"),),
                        facts={},
                    )
                ]

            def product_of_directory(self, root, directory):
                return DirectoryMatch()

            def classify_part(self, design, part, directory, manifest, *, verify=True):
                return PartVerdict.missing()

            def fetch_part(self, design, part, directory, **kw):
                raise SourceUnavailableError(
                    "manualsrc publishes no downloadable packages: obtain the "
                    "files by hand and register them with "
                    "stellariso.register_local_product()"
                )

        register_adapter(ManualAdapter())
        try:
            with pytest.raises(SourceUnavailableError, match="publishes no downloadable"):
                build_database(tmp_path / "db", models=["manualsrc"])
        finally:
            unregister_adapter("manualsrc")


class TestOpenDatabase:
    def test_open_and_grid(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, models=["mist"], session=session)
        db = open_database(db_path)
        assert len(db.products) == 2
        grid = db.grid("mist/1.2", label="vvcrit0.4_full_isos")
        assert isinstance(grid, IsochroneGrid)
        assert len(grid) > 0
        prov = db.provenance("mist/1.2", label="vvcrit0.4_full_isos")
        assert prov.data_sources[0].url.endswith(".txz")

    def test_unqualified_model_rejected(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, models=["mist"], session=session)
        db = open_database(db_path)
        with pytest.raises(ValueError, match="version-qualified"):
            db.grid("mist")

    def test_ambiguous_products_require_label(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, models=["mist"], session=session)
        db = open_database(db_path)
        with pytest.raises(ValueError, match="pin one"):
            db.grid("mist/1.2")

    def test_missing_release_lists_present_products(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, models=["mist"], session=session)
        db = open_database(db_path)
        with pytest.raises(SourceUnavailableError, match="holds no"):
            db.grid("mist/2.5", label="vvcrit0.4_full_isos")

    def test_partial_copy_is_portable(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, models=["mist"], session=session)
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

    def test_construct_from_database(self, fake_env):
        session, db_path = fake_env
        build_database(db_path, models=["mist"], session=session)
        mist = construct("mist/1.2", database=db_path, label="vvcrit0.4_full_isos")
        assert isinstance(mist, MistIso)
        assert mist.identity.release == "1.2"
        # absent release in the database fails listing what is present
        with pytest.raises(SourceUnavailableError, match="holds no mist/2.5"):
            construct("mist/2.5", database=db_path, label="vvcrit0.4_full_isos")
        # a stated release that contradicts the files' own identity fails too
        with pytest.raises(ValueError, match="does not match the data"):
            construct("mist/2.5", paths=[MIST_FIXTURE])

    def test_archives_only_build_and_lazy_extraction(self, fake_env):
        session, db_path = fake_env
        # archives-only: nothing extracted at build time
        build_database(db_path, models=["mist"], session=session, extract=False)
        product_dir = db_path / "mist" / "1.2" / "vvcrit0.4_full_isos"
        manifest = json.loads(
            (product_dir / "MANIFEST.json").read_text(encoding="utf-8")
        )
        assert (product_dir / "MIST_v1.2_vvcrit0.4_full_isos.txz").exists()
        assert manifest["n_data_files"] == 0
        assert manifest["extracted"] is False
        # first open extracts, verifying the archive checksum first
        db = open_database(db_path)
        grid = db.grid("mist/1.2", label="vvcrit0.4_full_isos")
        assert len(grid) > 0
        manifest = json.loads(
            (product_dir / "MANIFEST.json").read_text(encoding="utf-8")
        )
        assert manifest["extracted"] is True
        assert manifest["n_data_files"] > 0
        # a tampered archive fails verification instead of extracting
        other = db_path / "mist" / "1.2" / "vvcrit0.0_full_isos"
        (other / "MIST_v1.2_vvcrit0.0_full_isos.txz").write_bytes(b"tampered")
        with pytest.raises(DataIntegrityError, match="sha256"):
            db.grid("mist/1.2", label="vvcrit0.0_full_isos")


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
        import stellariso.database.core as dbmod

        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            data = b"evil"
            info = tarfile.TarInfo(name="../evil.txt")
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
        archive = tmp_path / "evil.txz"
        archive.write_bytes(buf.getvalue())
        with pytest.raises(ValueError, match="escapes"):
            dbmod._safe_extract(archive, tmp_path / "out")


class TestZipProductsAndCaBundle:
    def test_build_zip_archive_product(self, tmp_path, monkeypatch):
        import zipfile

        dat_a = b"# a data file inside a zip product\n1.0 2.0 3.0\n"
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("output1.dat", dat_a)
            zf.writestr("readme.txt", "notes")
        zip_catalog = {
            "family": "mist",
            "channel": "packages",
            "source_note": "test",
            "releases": [
                {
                    "release": "v1.2S",
                    "products": [
                        {
                            "label": "zipped_tables",
                            "kind": "isochrones",
                            "physics": {},
                            "filename": "zipped_tables.zip",
                            "url": "https://fake.example/zipped_tables.zip",
                            "size_bytes": len(buf.getvalue()),
                            "format": "cmd_table",
                        }
                    ],
                }
            ],
        }
        session = FakeStreamSession({zip_catalog["releases"][0]["products"][0]["url"]: buf.getvalue()})
        monkeypatch.setattr(
            "stellariso.models.mist.design.load_catalog", lambda family: zip_catalog
        )
        db = build_database(tmp_path / "db", session=session, models=["mist"])
        assert len(db.products) == 1
        product_dir = tmp_path / "db" / "mist" / "v1.2S" / "zipped_tables"
        assert (product_dir / "zipped_tables.zip").exists()
        assert (product_dir / "output1.dat").exists()
        manifest = json.loads((product_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["n_data_files"] == 1

    def test_default_session_gets_declared_ca_bundle(self, tmp_path):
        from stellariso.models.parsec.design import ParsecAdapter

        session = ParsecAdapter().default_session(tmp_path / "db")
        bundle = Path(session.verify)
        assert bundle.exists()
        import certifi

        content = bundle.read_bytes()
        certifi_pem = Path(certifi.where()).read_bytes()
        shipped = (
            Path(stellariso.__file__).parent
            / "models" / "parsec" / "ZeroSSLRSADVSSLCA2.crt"
        ).read_bytes()
        assert certifi_pem[:100] in content
        assert shipped in content  # the bundled intermediate was appended
        assert content.count(b"BEGIN CERTIFICATE") == (
            certifi_pem.count(b"BEGIN CERTIFICATE")
            + shipped.count(b"BEGIN CERTIFICATE")
        )


class TestFormProducts:
    """Form-channel families build through the same universal loop
    (tests/parsec/test_build.py covers the cell behavior itself; these
    pin the dispatch and the dry-run plan)."""

    def test_build_submits_through_the_adapter(self, tmp_path, monkeypatch):
        from stellariso.models.parsec import blueprint as bp
        from stellariso.models.parsec.design import ParsecAdapter
        from tests.parsec.test_build import StubClient

        cell = bp.Cell(set=bp.TRACK_SETS["v1.2S_COLIBRI_web"], mh=0.0, omega=0.0)
        adapter = ParsecAdapter()
        client = StubClient()
        monkeypatch.setattr(
            ParsecAdapter,
            "committed",
            lambda self: iter([adapter._design_of_cell(cell)]),
        )
        monkeypatch.setattr(
            ParsecAdapter, "fetch_client", lambda self, session=None: client
        )
        db = build_database(tmp_path / "db", models=["parsec"], form_pause=0.0)
        assert len(client.submissions) == 2  # both age grids, log first
        assert client.submissions[0]["isoc_isagelog"] == "1"
        assert len(db.products) == 1
        directory = tmp_path / "db" / "parsec" / cell.set.key / cell.label
        assert (directory / "output.dat").exists()
        assert (directory / "output_linear.dat").exists()

    def test_dry_run_reports_the_fetch_plan_without_submitting(
        self, tmp_path, capsys
    ):
        build_database(tmp_path / "db", dry_run=True)
        out = capsys.readouterr().out
        assert "471 fetch-stage cells" in out
        assert "942 form submissions" in out
