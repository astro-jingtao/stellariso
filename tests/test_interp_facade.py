"""Tests for within-isochrone interpolation and the unified facade."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pytest

from stellariso.exceptions import UnsafeInterpolationError
from stellariso.facade import MistIso, UnifiedIso, construct
from stellariso.grid import IsochroneGrid
from stellariso.interp import interpolate_along
from stellariso.warnings import NearestGridPointWarning, PhaseMappingWarning

FIXTURE = (
    Path(__file__).parent / "data" / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
)


@pytest.fixture(scope="module")
def grid():
    return IsochroneGrid.from_paths("mist", [FIXTURE])


@pytest.fixture(scope="module")
def iso(grid):
    return grid.get_isochrone(log_age=9.0, initial_feh=-1.0)


class TestInterpolateAlong:
    def test_linear_reproduces_nodes(self, iso):
        masses = iso.native["initial_mass"]
        out, record = interpolate_along(
            iso, "initial_mass", masses[:5], ["log_surface_gravity"]
        )
        assert np.allclose(out["log_surface_gravity"], iso.native["log_g"][:5])

    def test_linear_between_nodes(self, iso):
        m = iso.native["initial_mass"]
        mid = 0.5 * (m[10] + m[11])
        out, _ = interpolate_along(iso, "initial_mass", mid, "log_g")
        expected = 0.5 * (
            iso.native["log_g"][10] + iso.native["log_g"][11]
        )
        assert out["log_g"][0] == pytest.approx(expected)

    def test_unified_field_interpolation(self, iso):
        m = iso.native["initial_mass"]
        mid = 0.5 * (m[10] + m[11])
        out, _ = interpolate_along(iso, "initial_mass", mid, "radius")
        expected = 0.5 * (
            10.0 ** iso.native["log_R"][10] + 10.0 ** iso.native["log_R"][11]
        )
        assert out["radius"][0] == pytest.approx(expected)

    def test_pchip_method(self, iso):
        m = iso.native["initial_mass"]
        mid = 0.5 * (m[10] + m[11])
        out, _ = interpolate_along(
            iso, "initial_mass", mid, "log_Teff", method="pchip"
        )
        # pchip must lie between the bracketing node values (monotonic data)
        lo, hi = sorted(
            (iso.native["log_Teff"][10], iso.native["log_Teff"][11])
        )
        assert lo - 1e-6 <= out["log_Teff"][0] <= hi + 1e-6

    def test_extrapolation_refused(self, iso):
        with pytest.raises(UnsafeInterpolationError, match="outside"):
            interpolate_along(iso, "initial_mass", 1e6, "log_g")

    def test_unknown_field(self, iso):
        with pytest.raises(KeyError, match="neither a unified field"):
            interpolate_along(iso, "initial_mass", 1.0, "nope")

    def test_unknown_method(self, iso):
        with pytest.raises(ValueError, match="method"):
            interpolate_along(iso, "initial_mass", 1.0, "log_g", method="cubic")

    def test_record_content(self, iso):
        m = iso.native["initial_mass"]
        mid = 0.5 * (m[10] + m[11])
        out, record = interpolate_along(iso, "initial_mass", mid, ["log_g"])
        assert record.method == "linear"
        assert record.coordinate == "initial_mass"
        assert record.node_indices[0] == (10, 11)
        assert record.node_values[0] == (m[10], m[11])
        assert record.node_phases[0] == (
            iso.native["phase"][10],
            iso.native["phase"][11],
        )
        assert record.to_dict()["fields"] == ["log_g"]


class TestIsoAt:
    def test_at_single_field(self, iso):
        m = iso.native["initial_mass"][5]
        value = iso.at(m, "log_g")
        assert value == pytest.approx(iso.native["log_g"][5])

    def test_at_all_fields_with_record(self, iso):
        m = 0.5 * (
            iso.native["initial_mass"][5] + iso.native["initial_mass"][6]
        )
        values, record = iso.at(m, record=True)
        assert "log_surface_gravity" in values
        assert "radius" in values
        assert record.method == "linear"

    def test_at_initial_mass_alias(self, iso):
        m = iso.native["initial_mass"][5]
        assert iso.at_initial_mass(m, "log_Teff") == pytest.approx(
            iso.native["log_Teff"][5]
        )


class TestFacade:
    def test_abstract_class_in_hierarchy(self):
        assert issubclass(MistIso, UnifiedIso)
        assert issubclass(UnifiedIso, IsochroneGrid)

    def test_construct_dispatch_rejects_unknown(self):
        from stellariso.exceptions import UnsupportedModelError

        with pytest.raises(UnsupportedModelError):
            construct("nonexistent")

    def test_construct_from_paths(self):
        xx = construct("mist", paths=[FIXTURE])
        assert isinstance(xx, MistIso)
        assert xx.model_name == "mist"
        assert len(xx) == 2

    def test_get_logg_end_to_end(self):
        xx = construct("mist", paths=[FIXTURE])
        logg = xx.get_logg(mass=1.0, log_age=9.0, initial_feh=-1.0)
        assert np.isfinite(logg)
        record = xx.last_record
        assert record.method == "linear"
        assert record.coordinate == "initial_mass"

    def test_get_nearest_selection_warns_and_records(self):
        xx = construct("mist", paths=[FIXTURE])
        with pytest.warns(NearestGridPointWarning):
            logg = xx.get_logg(mass=1.0, log_age=9.3, initial_feh=-1.0)
        assert np.isfinite(logg)

    def test_get_detailed_returns_record(self):
        xx = construct("mist", paths=[FIXTURE])
        value, record = xx.get_detailed(
            "log_effective_temperature", 1.0, log_age=9.0, initial_feh=-1.0
        )
        assert np.isfinite(value)
        assert record.requested[0] == pytest.approx(1.0)

    def test_get_phase(self):
        xx = construct("mist", paths=[FIXTURE])
        # pick a mass deep inside the MS span of the age-9 isochrone
        masses = xx.get_isochrone(log_age=9.0).native["initial_mass"]
        m_ms = masses[len(masses) // 4]
        stage = xx.get_phase(m_ms, log_age=9.0, initial_feh=-1.0)
        assert stage in ("main_sequence", "red_giant_branch")

    def test_describe(self):
        xx = construct("mist", paths=[FIXTURE])
        text = xx.describe()
        assert "MistIso" in text
        assert "log_age" in text


class TestConstructFetch:
    def test_construct_subset_requires_args(self):
        with pytest.raises(ValueError, match="paths=.*feh="):
            construct("mist")

    def test_construct_fetches_through_fake_session(self, tmp_path):
        from .test_retrieval import FakeSession

        payload = FIXTURE.read_bytes()
        session = FakeSession(payload)
        xx = construct(
            "mist",
            feh=-1.0,
            log_ages=[9.0, 10.0],
            cache_dir=tmp_path,
            session=session,
        )
        assert isinstance(xx, MistIso)
        assert len(xx) == 2
        # a second construct hits the cache, not the network
        n_calls = len(session.calls)
        construct(
            "mist", feh=-1.0, log_ages=[9.0, 10.0], cache_dir=tmp_path, session=session
        )
        assert len(session.calls) == n_calls
