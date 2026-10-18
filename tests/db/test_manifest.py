"""Tests for MANIFEST v2: read bridge, v2-only writes, whole-database
upgrade (lossless cases and refusals)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stellariso.database.manifest import (
    SCHEMA,
    is_v2,
    load_raw,
    normalize,
    primary_part,
    read_manifest,
    upgrade_manifests,
    write_manifest,
)
from stellariso.exceptions import ManifestError


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


RUN4_PACKAGE = {
    "family": "mist",
    "release": "1.2",
    "label": "vvcrit0.4_full_isos",
    "kind": "isochrones",
    "physics": {"vvcrit": 0.4},
    "url": "https://mist.science/x.txz",
    "sha256": "a" * 64,
    "size_bytes": 123,
    "expected_size_bytes": 100,
    "n_data_files": 2,
    "extracted": True,
    "retrieved_at": "2026-10-01T00:00:00Z",
    "source_class": "official_origin",
    "note": "pkg",
    "format": "isochrones",
    "references": ["ref"],
}

RUN4_FORM = {
    "family": "parsec",
    "release": "v1.2S +  COLIBRI S_37 + S_35 + PR16",
    "label": "mh_p0.0",
    "kind": "cmd_form_isochrones",
    "sha256": "b" * 64,
    "size_bytes": 10,
    "n_data_rows": 177,
    "acquisition_record": "output.dat.record.json",
    "url": "https://stev/x",
    "retrieved_at": "2026-10-02T00:00:00Z",
    "source_class": "official_computed",
}

BLUEPRINT_FORM = {
    **RUN4_FORM,
    "sha256": "c" * 64,
    "blueprint": {
        "module": "stellariso.models.parsec.blueprint",
        "set": "v1.2S_COLIBRI_web",
        "axes": {"mh": 0.0},
        "age_grids": {"log": {"isochrones": 177}},
        "parts": {
            "log": {"file": "output.dat", "sha256": "c" * 64, "size_bytes": 10},
            "linear": {"file": "output_linear.dat", "sha256": "d" * 64},
        },
    },
}


class TestBridge:
    def test_run4_package_synthesizes_archive_part(self, tmp_path: Path):
        path = _write(tmp_path / "m" / "f" / "l" / "MANIFEST.json", RUN4_PACKAGE)
        view = read_manifest(path)
        assert is_v2(view) is False  # the view is not itself marked v2
        assert view["parts"]["archive"]["sha256"] == "a" * 64
        assert view["parts"]["archive"]["size_bytes"] == 123
        assert view["parts"]["archive"].get("file") is None  # design names the file
        assert primary_part(view) == "archive"

    def test_run4_form_synthesizes_log_part(self, tmp_path: Path):
        path = _write(tmp_path / "m" / "f" / "l" / "MANIFEST.json", RUN4_FORM)
        view = read_manifest(path)
        log = view["parts"]["log"]
        assert log["sha256"] == "b" * 64
        assert log["file"] == "output.dat"
        assert log["record"] == "output.dat.record.json"
        assert log["n_data_rows"] == 177
        assert primary_part(view) == "log"

    def test_blueprint_parts_win_over_flat_shadow(self, tmp_path: Path):
        path = _write(tmp_path / "m" / "f" / "l" / "MANIFEST.json", BLUEPRINT_FORM)
        view = read_manifest(path)
        assert set(view["parts"]) == {"log", "linear"}
        assert view["parts"]["log"]["sha256"] == "c" * 64

    def test_local_files_get_no_parts(self, tmp_path: Path):
        path = _write(
            tmp_path / "m" / "f" / "l" / "MANIFEST.json",
            {
                "family": "parsec",
                "release": "r",
                "label": "l",
                "kind": "local_user_files",
                "sha256": None,
                "files": ["a.dat"],
            },
        )
        view = read_manifest(path)
        assert view["parts"] == {}
        assert view["files"] == ["a.dat"]
        assert primary_part(view) is None

    def test_unknown_schema_refused(self, tmp_path: Path):
        path = _write(
            tmp_path / "m" / "f" / "l" / "MANIFEST.json",
            {"schema": "stellariso-manifest/3", "family": "mist"},
        )
        with pytest.raises(ManifestError, match="stellariso-manifest/3"):
            read_manifest(path)

    def test_v2_read_verbatim(self, tmp_path: Path):
        v2 = {"schema": SCHEMA, "family": "mist", "parts": {"archive": {"sha256": "e" * 64}}}
        path = _write(tmp_path / "m" / "f" / "l" / "MANIFEST.json", v2)
        assert read_manifest(path) == v2

    def test_unreadable_manifest_raises(self, tmp_path: Path):
        path = tmp_path / "m" / "f" / "l" / "MANIFEST.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ManifestError, match="not valid JSON"):
            read_manifest(path)


class TestWrite:
    def test_write_stamps_schema(self, tmp_path: Path):
        path = tmp_path / "MANIFEST.json"
        write_manifest(path, {"family": "mist", "parts": {}})
        raw = load_raw(path)
        assert raw["schema"] == SCHEMA
        assert is_v2(raw)

    def test_written_manifest_reads_back(self, tmp_path: Path):
        path = tmp_path / "MANIFEST.json"
        payload = {"family": "mist", "parts": {"archive": {"sha256": "f" * 64}}}
        write_manifest(path, payload)
        assert read_manifest(path)["parts"]["archive"]["sha256"] == "f" * 64


class TestUpgrade:
    @staticmethod
    def _db(tmp_path: Path, *manifests: tuple[str, dict]) -> Path:
        for rel, payload in manifests:
            _write(tmp_path / rel / "MANIFEST.json", payload)
        return tmp_path

    def test_package_manifest_upgraded_losslessly(self, tmp_path: Path):
        db = self._db(tmp_path, ("mist/1.2/prod", RUN4_PACKAGE))
        report = upgrade_manifests(db)
        assert report.upgraded == ["mist/1.2/prod"]
        assert report.ok
        raw = load_raw(db / "mist" / "1.2" / "prod" / "MANIFEST.json")
        assert raw["schema"] == SCHEMA
        assert raw["parts"]["archive"]["sha256"] == "a" * 64
        assert "sha256" not in raw  # the flat key moved, not duplicated
        assert raw["physics"] == {"vvcrit": 0.4}
        assert raw["n_data_files"] == 2  # local state survives
        # second run: nothing left to do
        assert upgrade_manifests(db).already_current == ["mist/1.2/prod"]

    def test_blueprint_manifest_upgraded_with_family_section(self, tmp_path: Path):
        db = self._db(tmp_path, ("parsec/web/mh_p0.0", BLUEPRINT_FORM))
        report = upgrade_manifests(db)
        assert report.ok
        raw = load_raw(db / "parsec" / "web" / "mh_p0.0" / "MANIFEST.json")
        assert "blueprint" not in raw
        assert raw["family_section"]["set"] == "v1.2S_COLIBRI_web"
        assert raw["family_section"]["axes"] == {"mh": 0.0}
        assert raw["parts"]["linear"]["sha256"] == "d" * 64

    def test_run4_form_upgraded(self, tmp_path: Path):
        db = self._db(tmp_path, ("parsec/web/mh_p0.0", RUN4_FORM))
        report = upgrade_manifests(db)
        assert report.ok
        raw = load_raw(db / "parsec" / "web" / "mh_p0.0" / "MANIFEST.json")
        assert raw["parts"]["log"]["record"] == "output.dat.record.json"

    def test_conflicting_shas_refused_and_untouched(self, tmp_path: Path):
        conflicted = json.loads(json.dumps(BLUEPRINT_FORM))
        conflicted["sha256"] = "z" * 64  # disagrees with blueprint parts log
        db = self._db(tmp_path, ("parsec/web/mh_p0.0", conflicted))
        before = (db / "parsec" / "web" / "mh_p0.0" / "MANIFEST.json").read_text(
            encoding="utf-8"
        )
        report = upgrade_manifests(db)
        assert [f.directory for f in report.failed] == ["parsec/web/mh_p0.0"]
        assert "conflicting sha256" in report.failed[0].reasons[0]
        after = (db / "parsec" / "web" / "mh_p0.0" / "MANIFEST.json").read_text(
            encoding="utf-8"
        )
        assert after == before  # refused means untouched

    def test_unknown_schema_refused(self, tmp_path: Path):
        db = self._db(
            tmp_path,
            ("mist/1.2/future", {"schema": "stellariso-manifest/3", "family": "mist"}),
        )
        report = upgrade_manifests(db)
        assert len(report.failed) == 1
        assert "not known" in report.failed[0].reasons[0]

    def test_missing_identity_refused(self, tmp_path: Path):
        db = self._db(tmp_path, ("mist/1.2/anon", {"sha256": "a" * 64}))
        report = upgrade_manifests(db)
        assert "no family identity" in report.failed[0].reasons[0]

    def test_dry_run_writes_nothing(self, tmp_path: Path):
        db = self._db(tmp_path, ("mist/1.2/prod", RUN4_PACKAGE))
        before = (db / "mist" / "1.2" / "prod" / "MANIFEST.json").read_text(
            encoding="utf-8"
        )
        report = upgrade_manifests(db, dry_run=True)
        assert report.upgraded == ["mist/1.2/prod"]
        assert report.dry_run is True
        assert (
            (db / "mist" / "1.2" / "prod" / "MANIFEST.json").read_text(encoding="utf-8")
            == before
        )

    def test_local_files_manifest_upgraded(self, tmp_path: Path):
        db = self._db(
            tmp_path,
            (
                "parsec/r/manual",
                {
                    "family": "parsec",
                    "release": "r",
                    "label": "manual",
                    "kind": "local_user_files",
                    "sha256": None,
                    "files": ["a.dat"],
                },
            ),
        )
        report = upgrade_manifests(db)
        assert report.ok
        raw = load_raw(db / "parsec" / "r" / "manual" / "MANIFEST.json")
        assert raw["parts"] == {}
        assert raw["files"] == ["a.dat"]
