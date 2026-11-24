"""Padova adapter tests: designs, classification, fetch (offline), and
the is_data_file hook (no network — downloads are faked)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from stellariso.database.core import Database, register_local_product
from stellariso.database.design import FamilyAdapter
from stellariso.integrity import sha256_bytes
from stellariso.models.padova.design import PadovaAdapter
from stellariso.warnings import (
    CatalogChecksumMismatchWarning,
    CatalogSizeMismatchWarning,
)


@pytest.fixture(scope="module")
def adapter() -> PadovaAdapter:
    return PadovaAdapter()


def _design(adapter: PadovaAdapter, release: str):
    return next(d for d in adapter.designs() if d.release == release)


def _part(design, name):
    return design.part_named(name)


class TestDesigns:
    def test_two_products_one_per_release(self, adapter):
        designs = list(adapter.designs())
        assert [d.release for d in designs] == ["1994", "2000"]
        assert all(d.label == "vizier_tables" for d in designs)
        assert all(d.family == "padova" for d in designs)
        assert all(d.kind == "isochrones" for d in designs)

    def test_parts_follow_the_catalog_files(self, adapter):
        p94 = _design(adapter, "1994")
        assert [p.name for p in p94.parts] == [
            "readme", "table1", "table2", "table3", "table4", "table5", "table6",
        ]
        p2000 = _design(adapter, "2000")
        assert [p.name for p in p2000.parts] == [
            "readme", "isochron", "isochsum",
        ]

    def test_every_part_carries_url_size_and_verified_sha(self, adapter):
        for design in adapter.designs():
            for part in design.parts:
                facts = design.facts["files"][part.name]
                assert facts["url"].startswith("http://vizier.nao.ac.jp/")
                assert facts["size_bytes"] > 0
                assert len(facts["sha256"]) == 64

    def test_directory_mapping(self, adapter, tmp_path):
        design = _design(adapter, "2000")
        directory = tmp_path / "padova" / "2000" / "vizier_tables"
        directory.mkdir(parents=True)
        match = adapter.product_of_directory(tmp_path, directory)
        assert match.matched
        assert match.design.key == design.key
        unknown = tmp_path / "padova" / "2000" / "mystery"
        match = adapter.product_of_directory(tmp_path, unknown)
        assert not match.matched
        assert "label" in match.superseded_reason
        stranger = tmp_path / "padova" / "1892" / "vizier_tables"
        match = adapter.product_of_directory(tmp_path, stranger)
        assert not match.matched
        assert "release" in match.superseded_reason


class TestClassify:
    @staticmethod
    def _place(directory: Path, filename: str, payload: bytes) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_bytes(payload)

    def test_missing_file_is_missing(self, adapter, tmp_path):
        design = _design(adapter, "1994")
        directory = tmp_path / design.relative_dir
        directory.mkdir(parents=True)
        verdict = adapter.classify_part(
            design, _part(design, "table1"), directory, {"parts": {}}
        )
        assert verdict.kind == "missing"

    def test_verified_part_with_matching_catalog_sha_is_clean(
        self, adapter, tmp_path
    ):
        design = _design(adapter, "1994")
        directory = tmp_path / design.relative_dir
        self._place(directory, "ReadMe", b"readme payload" * 100)
        entry = {"sha256": sha256_bytes(b"readme payload" * 100)}
        # the catalog's recorded size (5,981) does not match the stand-in
        # payload: that is a replaced-file tripwire, a warning not a failure
        verdict = adapter.classify_part(
            design, _part(design, "readme"), directory, {"parts": {"readme": entry}}
        )
        assert verdict.kind == "ok"
        assert any("bytes" in w for w in verdict.warnings)

    def test_manifest_sha_mismatch_is_nonconforming(self, adapter, tmp_path):
        design = _design(adapter, "1994")
        directory = tmp_path / design.relative_dir
        self._place(directory, "ReadMe", b"tampered")
        verdict = adapter.classify_part(
            design,
            _part(design, "readme"),
            directory,
            {"parts": {"readme": {"sha256": "0" * 64}}},
        )
        assert verdict.kind == "nonconforming"
        assert any("sha256" in r for r in verdict.reasons)

    def test_no_manifest_sha_warns(self, adapter, tmp_path):
        design = _design(adapter, "1994")
        directory = tmp_path / design.relative_dir
        self._place(directory, "ReadMe", b"payload")
        verdict = adapter.classify_part(
            design, _part(design, "readme"), directory, {"parts": {}}
        )
        assert verdict.kind == "ok"
        assert any("not verified" in w for w in verdict.warnings)

    def test_classification_without_a_cache_still_hashes(self, adapter, tmp_path):
        design = _design(adapter, "1994")
        directory = tmp_path / design.relative_dir
        self._place(directory, "ReadMe", b"payload")
        verdict = adapter.classify_part(
            design,
            _part(design, "readme"),
            directory,
            {"parts": {"readme": {"sha256": "0" * 64}}},
        )
        assert verdict.kind == "nonconforming"  # no skip-verify path exists


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for i in range(0, len(self._payload), chunk_size):
            yield self._payload[i : i + chunk_size]


class _FakeSession:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.requested = []

    def get(self, url, stream=True, timeout=None):
        self.requested.append(url)
        return _FakeResponse(self._payload)


class TestFetch:
    def test_fetch_keeps_gz_and_decompresses(self, adapter, tmp_path):
        design = _design(adapter, "1994")
        directory = tmp_path / design.relative_dir
        directory.mkdir(parents=True)
        payload = gzip.compress(b"table rows\n" * 10)
        session = _FakeSession(payload)
        # the stand-in payload necessarily differs from the catalog's
        # verified values: the replaced-file tripwires fire (and warn)
        with pytest.warns(
            (CatalogChecksumMismatchWarning, CatalogSizeMismatchWarning)
        ):
            entry = adapter.fetch_part(
                design, _part(design, "table1"), directory, session=session
            )
        assert session.requested == [
            "http://vizier.nao.ac.jp/ftp/cats/J/A+AS/106/275/table1.gz"
        ]
        assert (directory / "table1.gz").read_bytes() == payload
        assert (directory / "table1").read_bytes() == b"table rows\n" * 10
        assert entry["sha256"] == sha256_bytes(payload)
        assert entry["decompressed"] == "table1"
        assert entry["url"].endswith("table1.gz")
        assert entry["retrieved_at"]

    def test_fetch_warns_when_catalog_values_drift(self, adapter, tmp_path):
        design = _design(adapter, "1994")
        directory = tmp_path / design.relative_dir
        directory.mkdir(parents=True)
        session = _FakeSession(gzip.compress(b"replacement content"))
        with pytest.warns(
            (CatalogChecksumMismatchWarning, CatalogSizeMismatchWarning)
        ):
            entry = adapter.fetch_part(
                design, _part(design, "table1"), directory, session=session
            )
        # the fresh sha is recorded as the integrity anchor regardless
        assert entry["sha256"] == sha256_bytes(gzip.compress(b"replacement content"))
        assert entry["catalog_sha256"] != entry["sha256"]

    def test_plain_readme_part_has_no_decompression(self, adapter, tmp_path):
        design = _design(adapter, "2000")
        directory = tmp_path / design.relative_dir
        directory.mkdir(parents=True)
        with pytest.warns(
            (CatalogChecksumMismatchWarning, CatalogSizeMismatchWarning)
        ):
            entry = adapter.fetch_part(
                design, _part(design, "readme"), directory, session=_FakeSession(b"ReadMe text")
            )
        assert "decompressed" not in entry
        assert (directory / "ReadMe").read_bytes() == b"ReadMe text"


class TestManifestAndReport:
    def test_manifest_fields(self, adapter):
        design = _design(adapter, "2000")
        fields = adapter.manifest_fields(design)
        assert fields["source_class"] == "scientific_archive"
        assert "J/A+AS/141/371" in fields["note"]
        assert fields["format"] == "isochrones_2000"
        assert any("Girardi" in c for c in fields["references"])

    def test_family_section(self, adapter):
        section = adapter.family_section(_design(adapter, "1994"))
        assert section["vizier_catalog"] == "J/A+AS/106/275"
        assert section["channel"] == "adac_mirror_native_tree"

    def test_fetch_cost_is_a_download(self, adapter):
        design = _design(adapter, "2000")
        cost = adapter.fetch_cost(design, _part(design, "isochron"))
        assert cost == {"kind": "download", "size_bytes": 2894512}

    def test_report_header_declares_the_source(self, adapter):
        lines = adapter.report_header(list(adapter.designs()))
        assert any("VizieR" in line for line in lines)
        assert any("pleiadi" in line for line in lines)
        assert any("Total published size" in line for line in lines)


class TestIsDataFile:
    def test_padova_native_names_count_as_data(self, adapter, tmp_path):
        for name in (
            "table1", "table6", "table5.gz", "isochron.dat", "isochsum.dat",
            "isochron.dat.gz",
        ):
            assert adapter.is_data_file(tmp_path / name), name
        for name in ("ReadMe", "MANIFEST.json", "table1.gz.record.json", "z02.pst"):
            assert not adapter.is_data_file(tmp_path / name), name

    def test_default_hook_keeps_the_generic_rule(self):

        default = FamilyAdapter()
        assert default.is_data_file(Path("a.iso"))
        assert default.is_data_file(Path("b.dat.gz"))
        assert not default.is_data_file(Path("c.txt"))
        assert not default.is_data_file(Path("table1"))

    def test_database_grid_opens_padova_without_archive_logic(self, tmp_path):
        """_ensure_extracted's early return now consults the family hook:
        a padova product of plain extension-less tables is data-present
        and opens, where the generic suffix rule would have looked for
        an archive to extract."""

        fixture = Path(__file__).parent.parent / "data" / "padova" / "p1994"
        record = register_local_product(
            tmp_path,
            "padova",
            "1994",
            "hand_tables",
            files=[fixture / "table5"],
            note="test registration of one hand-held table",
        )
        db = Database(tmp_path)
        grid = db.grid("padova/1994", label="hand_tables")
        assert len(grid) == 4
        assert record.directory == tmp_path / "padova" / "1994" / "hand_tables"
