"""Unified-layer tests for the two padova products."""

from __future__ import annotations

from pathlib import Path
import shutil

import numpy as np
import pytest

from stellariso.core import FieldOrigin
from stellariso.exceptions import SourceUnavailableError
from stellariso.models.padova.backend import (
    MBOL_SUN_1994,
    Z_REFERENCE_1994,
    Z_REFERENCE_2000,
    invert_flum,
    read_padova,
)

DATA = Path(__file__).parent.parent / "data" / "padova"


@pytest.fixture(scope="module")
def set_2000():
    return read_padova(DATA / "p2000" / "isochron.dat")


@pytest.fixture(scope="module")
def set_1994():
    return read_padova(DATA / "p1994" / "table5")


def _iso(set_, **coords):
    for iso in set_:
        if all(iso.selection[k] == v for k, v in coords.items()):
            return iso
    raise KeyError(coords)


class TestPadova2000Unified:
    def test_native_direct_fields(self, set_2000):
        iso = _iso(set_2000, log_age=9.0, initial_z=0.019, overshoot=1.0)
        u, nt = iso.unified, iso.native
        assert np.array_equal(u["initial_mass"], nt["Mini"])
        assert np.array_equal(u["current_mass"], nt["Mact"])
        assert np.array_equal(u["log_luminosity"], nt["logL"])
        assert np.array_equal(u["log_effective_temperature"], nt["logTeff"])
        assert np.array_equal(u["log_surface_gravity"], nt["logg"])
        assert np.allclose(u["effective_temperature"], 10.0 ** nt["logTeff"])

    def test_field_origins(self, set_2000):
        iso = _iso(set_2000, log_age=9.0, initial_z=0.019, overshoot=1.0)
        assert iso.field_info("initial_mass").origin is FieldOrigin.NATIVE
        assert iso.field_info("phase").origin is FieldOrigin.DERIVED
        assert iso.field_info("native_phase").origin is FieldOrigin.MISSING
        assert iso.field_info("log_radius").origin is FieldOrigin.MISSING

    def test_phase_anchored_on_isochsum_points(self, set_2000):
        iso = _iso(set_2000, log_age=9.0, initial_z=0.019, overshoot=1.0)
        u = iso.unified
        # anchors of this isochrone: TO 1.7933, RGBb 2.0728, RGBt 2.0866,
        # EHeb 2.2986, 1TP 2.308 (BHeb 2.0913 collapses into the RGBt
        # boundary: the first present alias wins the chain slot)
        probes = {
            1.0: "main_sequence",
            1.9: "subgiant",
            2.08: "red_giant_branch",
            2.09: "core_helium_burning",
            2.30: "early_asymptotic_giant_branch",
            2.31: "thermally_pulsing_asymptotic_giant_branch",
        }
        mini = np.asarray(u["initial_mass"], dtype=float)
        for mass, stage in probes.items():
            i = int(np.searchsorted(mini, mass, side="right")) - 1
            assert u["phase"][i] == stage, (mass, i, u["phase"][i])

    def test_missing_anchor_extends_stage(self, set_2000):
        # the young isochrone (7.80) has no 1TP: its most massive rows
        # stay in early_asymptotic_giant_branch through the C-ignition end
        iso = _iso(set_2000, log_age=7.8, initial_z=0.019, overshoot=1.0)
        u = iso.unified
        assert u["phase"][-1] == "early_asymptotic_giant_branch"
        assert "thermally_pulsing_asymptotic_giant_branch" not in set(u["phase"])

    def test_phase_without_summary_companion_fails_loudly(
        self, set_2000, tmp_path
    ):
        lone = tmp_path / "isochron.dat"
        shutil.copy(DATA / "p2000" / "isochron.dat", lone)
        lone_set = read_padova(lone)
        iso = lone_set[0]
        # every native field still works
        assert iso.unified["initial_mass"][0] == pytest.approx(0.15, abs=1e-4)
        with pytest.raises(SourceUnavailableError, match="isochsum"):
            iso.unified["phase"]

    def test_selection_keys(self, set_2000):
        iso = _iso(set_2000, log_age=10.0, initial_z=0.019, overshoot=1.0)
        # the source's own Z is the composition coordinate; [Fe/H] stays
        # a derived parameter, never a selection key
        assert iso.selection["initial_z"] == pytest.approx(0.019)
        assert iso.selection["overshoot"] == 1.0
        assert "initial_feh" not in iso.selection
        assert iso.native.metadata["z_values"] == (0.004, 0.019)

    def test_parameters(self, set_2000):
        feh = set_2000.parameter("initial_feh")
        assert feh.relation == "log10(initial_z / Z_ref)"
        assert feh.relation_parameters == {"Z_ref": Z_REFERENCE_2000}
        assert set_2000.parameter("overshoot").values == (0.0, 1.0)
        assert set_2000.parameter("initial_helium").values == (0.24, 0.273)
        assert set_2000.parameter("initial_rotation").role.value == "not_applicable"
        assert set_2000.parameter("eta_reimers").role.value == "implicit"


class TestPadova1994Unified:
    def test_initial_mass_is_flum_inversion(self, set_1994):
        iso = _iso(set_1994, log_age=9.0)
        assert np.allclose(
            iso.unified["initial_mass"],
            invert_flum(iso.native["FLUM"]),
        )

    def test_initial_mass_monotone_hard_invariant(self, set_1994):
        # the consumer chain finite-differences along initial_mass; every
        # block of the archive must satisfy it after inversion
        for iso in set_1994:
            mini = np.asarray(iso.unified["initial_mass"], dtype=float)
            assert np.all(np.diff(mini) >= -1e-12)

    def test_current_mass_wind_branch(self, set_1994):
        iso = _iso(set_1994, log_age=7.0)
        wind = np.asarray(iso.native["Mwind"]) > 0
        assert wind.any()
        expected = np.where(wind, iso.native["Mwind"], iso.native["M"])
        assert np.array_equal(iso.unified["current_mass"], expected)
        # and no wind rows exist in the old block
        old = _iso(set_1994, log_age=10.0)
        assert not (np.asarray(old.native["Mwind"]) > 0).any()

    def test_log_luminosity_zero_point(self, set_1994):
        iso = _iso(set_1994, log_age=9.0)
        expected = (MBOL_SUN_1994 - iso.native["Mbol"]) / 2.5
        assert np.allclose(iso.unified["log_luminosity"], expected)

    def test_logg_closure_formula(self, set_1994):
        iso = _iso(set_1994, log_age=9.0)
        u = iso.unified
        expected = (
            np.log10(u["current_mass"])
            + 4.0 * (u["log_effective_temperature"] - np.log10(5777.0))
            - u["log_luminosity"]
            + 4.438
        )
        assert np.allclose(u["log_surface_gravity"], expected)

    def test_phase_shape_rules_old_block(self, set_1994):
        iso = _iso(set_1994, log_age=10.0)
        u = iso.unified
        mini = np.asarray(u["initial_mass"], dtype=float)
        i_ms = int(np.searchsorted(mini, 0.8, side="right")) - 1
        assert u["phase"][i_ms] == "main_sequence"
        i_rgb = int(np.searchsorted(mini, 1.05, side="right")) - 1
        assert u["phase"][i_rgb] == "red_giant_branch"
        # the isochrone ends as a cooling white dwarf
        assert u["phase"][0] == "main_sequence"
        assert u["phase"][-1] == "white_dwarf"
        assert "post_agb" in set(u["phase"])
        # the subgiant branch is deliberately not separated (no source
        # anchor; the MIST phase-2 precedent merges it into the RGB)
        assert "subgiant" not in set(u["phase"])

    def test_wolf_rayet_rows_in_youngest_block(self, set_1994):
        iso = _iso(set_1994, log_age=6.7)
        stages = iso.unified["phase"]
        wr = np.asarray(stages) == "wolf_rayet"
        assert wr.any()
        # stripped cores: massive and hotter than the turnoff
        mini = np.asarray(iso.unified["initial_mass"])
        log_teff = np.asarray(iso.unified["log_effective_temperature"])
        assert (mini[wr] > 10.0).all()
        assert (log_teff[wr] > log_teff[~wr].max() - 0.1).all()
        # and no other block carries them
        for other in set_1994:
            if other.selection["log_age"] != 6.7:
                assert "wolf_rayet" not in set(other.unified["phase"])

    def test_phase_young_block_has_no_remnant_stages(self, set_1994):
        iso = _iso(set_1994, log_age=7.0)
        stages = set(iso.unified["phase"])
        assert "post_agb" not in stages
        assert "white_dwarf" not in stages
        assert {"main_sequence", "red_giant_branch"} <= stages

    def test_field_origins(self, set_1994):
        iso = _iso(set_1994, log_age=9.0)
        assert iso.field_info("log_effective_temperature").origin is FieldOrigin.NATIVE
        assert iso.field_info("initial_mass").origin is FieldOrigin.DERIVED
        assert iso.field_info("current_mass").origin is FieldOrigin.DERIVED
        assert iso.field_info("log_luminosity").origin is FieldOrigin.DERIVED
        assert iso.field_info("log_surface_gravity").origin is FieldOrigin.DERIVED

    def test_parameters(self, set_1994):
        feh = set_1994.parameter("initial_feh")
        assert feh.relation_parameters == {"Z_ref": Z_REFERENCE_1994}
        assert set_1994.parameter("initial_z").values == (0.02,)
        assert set_1994.parameter("initial_helium").values == (0.28,)
        assert set_1994.parameter("overshoot").role.value == "implicit"
        assert set_1994.parameter("initial_feh").values[0] == pytest.approx(0.0)


class TestProvenanceAndIdentity:
    def test_identity_labels(self, set_2000, set_1994):
        assert set_2000.identity.label == "padova/2000"
        assert set_1994.identity.label == "padova/1994"
        assert set_2000.identity.product == "theoretical_isochrones"

    def test_citations_attached(self, set_2000):
        citations = {r.citation for r in set_2000.provenance.scientific_references}
        assert any("Girardi" in c for c in citations)
        assert any("Bertelli" in c for c in citations)

    def test_within_isochrone_interpolation(self, set_1994):
        iso = _iso(set_1994, log_age=9.0)
        value, record = iso.at(1.0, fields="log_surface_gravity", record=True)
        assert 3.0 < value < 5.0
        assert record.coordinate == "initial_mass"
        assert record.node_indices[0][1] == record.node_indices[0][0] + 1
