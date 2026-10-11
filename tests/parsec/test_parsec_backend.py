"""Tests for the PARSEC backend against the format-equivalent fixture."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from stellariso.core import ParameterRole
from stellariso.exceptions import SourceUnavailableError, UnrecognizedFormatError
from stellariso.facade import ParsecIso, construct
from stellariso.grid import IsochroneGrid, open_grid
from stellariso.models import get_backend

FIXTURE = Path(__file__).parent.parent / "data" / "parsec" / "parsec_cmd_v1p2S_fixture.dat"

read_parsec = get_backend("parsec").read
recognize_parsec = get_backend("parsec").recognize

GOLDEN = {
    "release": "v1.2S +  COLIBRI S_37 + S_35 + PR16",
    "eta_reimers": 0.2,
    "photsys": "UBVRIJHK",
    "z": 0.0152,
    "y": 0.2485 + 1.78 * 0.0152,
    "ages": (9.0, 9.5),
    "n_columns": 19,
    "n_rows_per_block": 40,
}


@pytest.fixture(scope="module")
def set_():
    return read_parsec(FIXTURE)


class TestReader:
    def test_header_facts(self, set_):
        f = set_.native.metadata
        assert f["release"] == GOLDEN["release"]
        assert f["eta_reimers"] == GOLDEN["eta_reimers"]
        assert f["photsys"] == GOLDEN["photsys"]

    def test_blocks_and_ages(self, set_):
        assert len(set_) == 2
        assert set_.keys() == list(GOLDEN["ages"])
        for iso in set_:
            assert len(iso) == GOLDEN["n_rows_per_block"]

    def test_columns(self, set_):
        cols = set_.native.columns
        assert len(cols) == GOLDEN["n_columns"]
        assert cols[:6] == ["log(age/yr)", "M_ini", "M_act", "logL/Lo", "logTe", "logG"]
        assert "label" in cols and "int_IMF" in cols

    def test_block_metadata_composition(self, set_):
        for meta in set_.native.block_metadata:
            assert meta["z"] == pytest.approx(GOLDEN["z"])
            assert meta["y"] == pytest.approx(GOLDEN["y"], rel=1e-3)

    def test_recognizer(self):
        assert recognize_parsec(FIXTURE)

    def test_recognizer_rejects_mist(self):
        mist = FIXTURE.parent.parent / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
        assert not recognize_parsec(mist)

    def test_garbage_rejected(self, tmp_path):
        bad = tmp_path / "garbage.dat"
        bad.write_text("# nothing recognizable\n1 2 3\n", encoding="ascii")
        with pytest.raises(UnrecognizedFormatError):
            read_parsec(bad)


class TestBackendObjects:
    def test_identity(self, set_):
        assert set_.identity.family == "parsec"
        assert "v1.2S" in set_.identity.release
        assert set_.identity.product == "cmd_isochrone_table"

    def test_parameters(self, set_):
        assert set_.parameter("log_age").role is ParameterRole.AXIS
        assert set_.parameter("log_age").values == GOLDEN["ages"]
        assert set_.parameter("initial_z").values == (GOLDEN["z"],)
        y = set_.parameter("initial_helium")
        assert y.role is ParameterRole.DERIVED
        assert y.relation == "Y_p + dYdZ * initial_z"
        assert y.relation_parameters["dYdZ"] == 1.78
        assert set_.parameter("alpha_fe").role is ParameterRole.FIXED
        assert set_.parameter("alpha_fe").value == 0.0
        rot = set_.parameter("initial_rotation")
        assert rot.role is ParameterRole.NOT_APPLICABLE
        assert set_.parameter("eta_reimers").value == 0.2

    def test_selection_pins(self, set_):
        iso = set_[0]
        assert iso.selection["log_age"] == 9.0
        assert iso.selection["initial_z"] == pytest.approx(GOLDEN["z"])

    def test_unified_fields(self, set_):
        iso = set_[0]
        assert np.array_equal(iso.unified["initial_mass"], iso.native["M_ini"])
        assert np.array_equal(iso.unified["current_mass"], iso.native["M_act"])
        assert np.array_equal(
            iso.unified["log_surface_gravity"], iso.native["logG"]
        )
        # every declared field resolves against real columns
        for name, spec in iso.field_specs.items():
            assert spec.native_name in iso.native.columns, name
            assert len(iso.unified[name]) == len(iso)

    def test_phase_mapping(self, set_):
        iso = set_[0]
        stages = iso.unified["phase"]
        label = iso.native["label"]
        assert set(stages[label == 1]) == {"main_sequence"}
        assert set(stages[label == 3]) == {"red_giant_branch"}
        assert set(stages[label == 4]) == {"core_helium_burning"}

    def test_provenance_references(self, set_):
        cites = " ".join(r.citation for r in set_.provenance.scientific_references)
        assert "Bressan" in cites and "Marigo" in cites


class TestGridAndFacade:
    def test_open_grid_autodetect(self):
        g = open_grid(FIXTURE)
        assert g.identity.family == "parsec"
        assert g.axis_values("log_age") == GOLDEN["ages"]
        assert g.axis_values("initial_z") == (GOLDEN["z"],)

    def test_grid_selection_by_z(self):
        g = IsochroneGrid.from_paths("parsec", [FIXTURE])
        iso = g.get_isochrone(log_age=9.0)
        assert iso.selection["log_age"] == 9.0

    def test_construct_and_get(self):
        xx = construct("parsec", paths=[FIXTURE])
        assert isinstance(xx, ParsecIso)
        logg = xx.get_logg(mass=1.0, log_age=9.0, initial_z=GOLDEN["z"])
        assert np.isfinite(logg)
        teff = xx.get_log_teff(mass=1.5, log_age=9.5, initial_z=GOLDEN["z"])
        assert np.isfinite(teff)
        assert xx.last_record.coordinate == "initial_mass"
        stage = xx.get_phase(mass=0.5, log_age=9.0, initial_z=GOLDEN["z"])
        assert stage == "main_sequence"

    def test_construct_requires_paths(self):
        with pytest.raises(ValueError, match="paths="):
            construct("parsec")

    def test_fetch_channel_is_manual(self):
        from stellariso.retrieval import fetch

        with pytest.raises(SourceUnavailableError, match="manually"):
            fetch("parsec", channel="manual")


class TestCrossModelParity:
    """The API behaves the same across backends; the models stay different."""

    def test_same_facade_shape(self):
        mist_fixture = (
            FIXTURE.parent.parent / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
        )
        m = construct("mist", paths=[mist_fixture])
        p = construct("parsec", paths=[FIXTURE])
        for xx in (m, p):
            assert hasattr(xx, "get_logg")
            assert hasattr(xx, "describe")
            assert xx.identity.product != ""
            assert xx.last_record is None
        # native differences preserved, not flattened
        assert "initial_feh" in m.axes
        assert "initial_z" in p.axes
        assert m.get_logg(mass=1.0, log_age=9.0, initial_feh=-1.0) != p.get_logg(
            mass=1.0, log_age=9.0, initial_z=GOLDEN["z"]
        )
