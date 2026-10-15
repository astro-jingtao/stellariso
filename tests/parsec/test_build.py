"""Offline tests for the blueprint-driven PARSEC cell builder.

A stub client answers from the real captured grid fixture (no network):
these tests pin the two-file cell layout, the extended MANIFEST, the
keep-verified rule, the no-mixed-grids guard, and run-4 directory
compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path

from stellariso.models.parsec import blueprint as bp
from stellariso.models.parsec.build import build_cell, fetch_plan
from stellariso.models.parsec.cmd_form import (
    CMD_ENDPOINTS,
    CmdFieldSet,
    CmdJob,
    CmdOutput,
)

WEB = bp.TRACK_SETS["v1.2S_COLIBRI_web"]
GRID_TABLE = (
    Path(__file__).parent.parent / "data" / "parsec" / "cmd_form" / "output_grid.dat"
).read_bytes()


class StubClient:
    """A CmdFormClient stand-in answering from the captured fixture."""

    def __init__(self, content: bytes | None = None):
        self.content = GRID_TABLE if content is None else content
        self.submissions: list[dict] = []

    def submit(self, fields):
        payload = fields.as_dict() if isinstance(fields, CmdFieldSet) else dict(fields)
        self.submissions.append(payload)
        return CmdJob(
            cmd_version="3.9",
            endpoint=CMD_ENDPOINTS["3.9"],
            fields=payload,
            submitted_at="2026-10-16T00:00:00Z",
            completed_at="2026-10-16T00:00:08Z",
            output_url="https://stev.oapd.inaf.it/tmp/outputSTUB.dat",
            output_name="outputSTUB.dat",
            retention_note="2 h",
        )

    def fetch_output(self, job):
        text = self.content.decode("utf-8", "replace")
        return CmdOutput(
            job=job,
            url=job.output_url,
            filename=job.output_name,
            content=self.content,
            sha256=_sha_bytes(self.content),
            retrieved_at="2026-10-16T00:00:09Z",
            comment_lines=tuple(
                ln for ln in text.splitlines() if ln.lstrip().startswith("#")
            ),
            n_data_rows=sum(
                1
                for ln in text.splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            ),
        )


def _sha_bytes(content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()


def _build(db: Path, cell: bp.Cell, **kw):
    client = kw.pop("client", StubClient())
    outcome = build_cell(db, cell, client=client, pause=0.0, log=lambda *_: None)
    return outcome, client


class TestFreshCell:
    def test_both_grids_fetched_into_one_directory(self, tmp_path: Path):
        cell = bp.Cell(set=WEB, mh=0.0, omega=0.0)
        outcome, client = _build(tmp_path, cell)
        assert outcome == "fetched"
        assert len(client.submissions) == 2
        # log grid first, linear second; payloads carry the axes
        log_payload, linear_payload = client.submissions
        assert log_payload["isoc_isagelog"] == "1"
        assert log_payload["eta_reimers"] == "0.2"
        assert linear_payload["isoc_isagelog"] == "0"
        assert linear_payload["isoc_dage"] == "1.0e5"
        directory = tmp_path / "parsec" / WEB.key / cell.label
        assert (directory / "output.dat").read_bytes() == GRID_TABLE
        assert (directory / "output_linear.dat").read_bytes() == GRID_TABLE
        assert (directory / "output.dat.record.json").exists()
        assert (directory / "output_linear.dat.record.json").exists()

    def test_extended_manifest(self, tmp_path: Path):
        cell = bp.Cell(set=WEB, mh=-1.0, omega=0.0, eta=0.4)
        _build(tmp_path, cell)
        manifest = json.loads(
            (
                tmp_path / "parsec" / WEB.key / cell.label / "MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        # legacy keys still describe the log-age table
        assert manifest["family"] == "parsec"
        assert manifest["release"] == WEB.release
        assert manifest["label"] == cell.label
        assert manifest["source_class"] == "official_computed"
        assert manifest["sha256"] == _sha_bytes(GRID_TABLE)
        assert manifest["n_data_files"] == 2
        # the blueprint section pins the cell identity and both parts
        section = manifest["blueprint"]
        assert section["set"] == WEB.key
        assert section["axes"] == {
            "mh": -1.0,
            "omega": 0.0,
            "eta_reimers": 0.4,
            "n_inTPC": bp.CANONICAL_N_INTPC,
            "dust_sourceM": bp.CANONICAL_DUST_M,
            "dust_sourceC": bp.CANONICAL_DUST_C,
            "kind_LPV": bp.CANONICAL_LPV,
        }
        assert section["age_grids"]["log"]["isochrones"] == bp.expected_log_ages()
        assert section["age_grids"]["linear"]["isochrones"] == bp.expected_linear_ages()
        assert set(section["parts"]) == {"log", "linear"}
        assert section["parts"]["log"]["file"] == "output.dat"
        assert section["parts"]["linear"]["file"] == "output_linear.dat"
        assert section["parts"]["log"]["sha256"] == _sha_bytes(GRID_TABLE)


class TestKeepVerified:
    def test_second_run_submits_nothing(self, tmp_path: Path):
        cell = bp.Cell(set=WEB, mh=0.0, omega=0.0)
        _build(tmp_path, cell)
        outcome, client = _build(tmp_path, cell)
        assert outcome == "kept"
        assert client.submissions == []

    def test_tampered_log_table_is_reacquired(self, tmp_path: Path):
        cell = bp.Cell(set=WEB, mh=0.0, omega=0.0)
        _build(tmp_path, cell)
        directory = tmp_path / "parsec" / WEB.key / cell.label
        (directory / "output.dat").write_bytes(b"tampered")
        outcome, client = _build(tmp_path, cell)
        assert outcome == "fetched"
        assert len(client.submissions) == 1  # only the log grid again
        assert (directory / "output.dat").read_bytes() == GRID_TABLE


class TestRun4Compatibility:
    def _legacy_dir(self, tmp_path: Path, cell: bp.Cell, payload: dict):
        """A run-4 style product directory: log table, record, flat sha."""
        directory = tmp_path / "parsec" / cell.set.key / cell.label
        directory.mkdir(parents=True)
        (directory / "output.dat").write_bytes(GRID_TABLE)
        (directory / "output.dat.record.json").write_text(
            json.dumps({"request_fields": payload}), encoding="utf-8"
        )
        (directory / "MANIFEST.json").write_text(
            json.dumps({"sha256": _sha_bytes(GRID_TABLE)}), encoding="utf-8"
        )
        return directory

    def test_conforming_legacy_cell_gets_only_linear(self, tmp_path: Path):
        cell = bp.Cell(set=WEB, mh=0.0, omega=0.0)
        self._legacy_dir(tmp_path, cell, bp.expected_payload(cell, "log"))
        outcome, client = _build(tmp_path, cell)
        assert outcome == "fetched"
        assert len(client.submissions) == 1
        assert client.submissions[0]["isoc_isagelog"] == "0"
        manifest = json.loads(
            (tmp_path / "parsec" / WEB.key / cell.label / "MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        # the legacy sha256 migrated into the blueprint parts
        assert manifest["blueprint"]["parts"]["log"]["sha256"] == _sha_bytes(GRID_TABLE)

    def test_non_conforming_legacy_cell_left_untouched(self, tmp_path: Path):
        cell = bp.Cell(set=WEB, mh=0.0, omega=0.0)
        coarse = dict(bp.expected_payload(cell, "log"), isoc_dlage="0.05")
        directory = self._legacy_dir(tmp_path, cell, coarse)
        before = sorted(p.name for p in directory.iterdir())
        outcome, client = _build(tmp_path, cell)
        assert outcome == "mismatch"
        assert client.submissions == []
        assert sorted(p.name for p in directory.iterdir()) == before


class TestFetchPlan:
    def test_plan_without_database(self, tmp_path: Path):
        plan = fetch_plan(tmp_path / "nonexistent")
        assert plan["target_cells"] == 471
        assert plan["submissions_to_target"] == 942

    @staticmethod
    def _synthetic_table(blocks: int) -> bytes:
        # the block counts the design expects, with the web header echo
        text = (
            "# File generated by CMD 3.9\n"
            "# isochrones based on PARSEC release v1.2S +  COLIBRI S_37 + S_35 + PR16\n"
            + "# Zini MH logAge Mini int_IMF Mass\n" * blocks
        )
        return text.encode()

    def test_plan_measures_an_existing_database(self, tmp_path: Path):
        cell = bp.Cell(set=WEB, mh=0.0, omega=0.0)
        content = {
            "log": self._synthetic_table(bp.expected_log_ages()),
            "linear": self._synthetic_table(bp.expected_linear_ages()),
        }

        class _TwoTableStub(StubClient):
            def submit(self, fields):
                which = "log" if fields.as_dict()["isoc_isagelog"] == "1" else "linear"
                self.content = content[which]
                return super().submit(fields)

        _build(tmp_path, cell, client=_TwoTableStub())
        (tmp_path / "database.json").write_text("{}", encoding="utf-8")
        plan = fetch_plan(tmp_path)
        # one complete cell: 940 submissions remain to the 942 target
        assert plan["submissions_to_target"] == 940

    def test_built_cell_opens_as_a_grid(self, tmp_path: Path):
        from stellariso.database import open_database

        # a log-only cell (run-4 shape: the real captured table) opens
        # through the database exactly as a run-4 product does
        cell = bp.Cell(set=WEB, mh=0.0, omega=0.0)
        directory = tmp_path / "parsec" / WEB.key / cell.label
        directory.mkdir(parents=True)
        (directory / "output.dat").write_bytes(GRID_TABLE)
        (directory / "output.dat.record.json").write_text(
            json.dumps({"request_fields": bp.expected_payload(cell, "log")}),
            encoding="utf-8",
        )
        (directory / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "family": "parsec",
                    "release": WEB.release,
                    "label": cell.label,
                    "sha256": _sha_bytes(GRID_TABLE),
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "database.json").write_text("{}", encoding="utf-8")
        db = open_database(tmp_path)
        grid = db.grid(f"parsec/{WEB.release}", label=cell.label)
        assert len(grid) == 3  # the fixture's age grid (2 compositions)
        assert len(db.products) == 1
