"""Tests for the unified layer and the MIST unified mapping."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from stellariso.core import FieldOrigin
from stellariso.exceptions import UnrecognizedFormatError
from stellariso.models.mist.backend import read_mist
from stellariso.unified import PhaseMapping, UnifiedView
from stellariso.warnings import PhaseMappingWarning

FIXTURE = (
    Path(__file__).parent.parent / "data" / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
)


@pytest.fixture(scope="module")
def set_():
    return read_mist(FIXTURE)


class TestUnifiedViewMist:
    def test_native_passthrough(self, set_):
        iso = set_[0]
        assert np.array_equal(iso.unified["initial_mass"], iso.native["initial_mass"])
        assert np.array_equal(
            iso.unified["log_surface_gravity"], iso.native["log_g"]
        )

    def test_transformed_radius(self, set_):
        iso = set_[0]
        assert np.allclose(iso.unified["radius"], 10.0 ** iso.native["log_R"])

    def test_transformed_teff(self, set_):
        iso = set_[0]
        assert np.allclose(
            iso.unified["effective_temperature"], 10.0 ** iso.native["log_Teff"]
        )

    def test_convenience_attribute_access(self, set_):
        iso = set_[0]
        assert np.array_equal(iso.log_surface_gravity, iso.native["log_g"])
        assert np.array_equal(iso.current_mass, iso.native["star_mass"])
        with pytest.raises(AttributeError):
            _ = iso.not_a_field

    def test_get_and_has_field(self, set_):
        iso = set_[0]
        assert iso.has_field("log_luminosity")
        assert not iso.has_field("not_a_field")
        assert np.array_equal(iso.get("log_luminosity"), iso.native["log_L"])

    def test_field_info_traceability(self, set_):
        iso = set_[0]
        spec = iso.field_info("current_mass")
        assert spec.native_name == "star_mass"
        assert spec.origin is FieldOrigin.NATIVE
        assert spec.backend == "mist"
        assert spec.mapping_version == "1"
        spec_r = iso.field_info("radius")
        assert spec_r.native_name == "log_R"
        assert spec_r.transformation == "10 ** x"
        assert spec_r.origin is FieldOrigin.TRANSFORMED_NATIVE
        with pytest.raises(KeyError):
            iso.field_info("not_a_field")

    def test_unified_to_table(self, set_):
        iso = set_[0]
        t = iso.unified.to_table()
        assert "initial_mass" in t.colnames
        assert "log_surface_gravity" in t.colnames
        assert "phase" in t.colnames
        assert t["radius"].unit is not None
        assert t.meta["stellariso_layer"] == "unified"
        assert "field_specs" in t.meta
        assert np.allclose(np.asarray(t["radius"]), 10.0 ** iso.native["log_R"])

    def test_phase_mapping_real_codes(self, set_):
        iso = set_[0]
        stages = iso.unified["phase"]
        native = iso.native["phase"]
        # fixture block 1 has codes -1,0,2,3,4,5,6
        assert set(stages[native == -1]) == {"pre_main_sequence"}
        assert set(stages[native == 0]) == {"main_sequence"}
        assert set(stages[native == 2]) == {"red_giant_branch"}
        assert set(stages[native == 3]) == {"core_helium_burning"}
        assert set(stages[native == 4]) == {"early_asymptotic_giant_branch"}
        assert set(stages[native == 5]) == {"thermally_pulsing_asymptotic_giant_branch"}
        assert set(stages[native == 6]) == {"post_agb"}

    def test_native_phase_preserved(self, set_):
        iso = set_[0]
        assert np.array_equal(iso.unified["native_phase"], iso.native["phase"])

    def test_phase_mapping_unmapped_warns(self):
        pm = PhaseMapping("mist", "1", {0: "main_sequence"})
        with pytest.warns(PhaseMappingWarning, match="no unified mapping"):
            out = pm(np.array([0, 42]))
        assert out[0] == "main_sequence"
        assert out[1] == "unknown"

    def test_phase_mapping_rejects_bad_stage_names(self):
        with pytest.raises(ValueError, match="non-standard"):
            PhaseMapping("mist", "1", {0: "dwarfish_branch"})


class TestMappingIntegrity:
    def test_every_spec_native_name_exists(self, set_):
        """Every non-missing field must resolve against real native columns."""
        for iso in set_:
            for name, spec in iso.field_specs.items():
                if spec.origin is FieldOrigin.MISSING:
                    continue
                assert spec.native_name in iso.native.columns, (
                    f"field {name!r} declares native_name {spec.native_name!r} "
                    "which the file does not carry"
                )

    def test_every_field_accessible(self, set_):
        for iso in set_:
            for name in iso.field_specs:
                values = iso.unified[name]
                assert len(values) == len(iso)


class TestPhysicsInvariants:
    """Cheap scientific validation on real data (Stefan-Boltzmann closure)."""

    def test_logL_teff_radius_consistency(self, set_):
        for iso in set_:
            logL = iso.unified["log_luminosity"]
            logT = iso.unified["log_effective_temperature"]
            logR = iso.unified["log_radius"]
            closure = logL - (4.0 * logT + 2.0 * logR)
            # L/Lsun = (T/Tsun)^4 (R/Rsun)^2 with Tsun=Rsun=1 in solar units;
            # file precision gives closure near -4.438... + 0 (we only check spread)
            assert np.nanmedian(np.abs(closure - np.nanmedian(closure))) < 1e-3

    def test_mass_loss_sign_convention(self, set_):
        # documented: star_mdot < 0 while losing mass; on the RGB the file
        # should carry some strictly negative values
        for iso in set_:
            rgb = iso.native["phase"] == 2
            if rgb.any():
                assert (iso.native["star_mdot"][rgb] < 0).any()
