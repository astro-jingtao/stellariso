"""Grid and facade tests for the padova family."""

from __future__ import annotations

from pathlib import Path

import pytest

import stellariso
from stellariso.exceptions import GridPointNotFoundError
from stellariso.warnings import NearestGridPointWarning

DATA = Path(__file__).parent.parent / "data" / "padova"
P2000_DIR = DATA / "p2000"
P1994_DIR = DATA / "p1994"


@pytest.fixture(scope="module")
def grid_2000():
    return stellariso.open_grid(P2000_DIR, model="padova/2000")


@pytest.fixture(scope="module")
def grid_1994():
    return stellariso.open_grid(P1994_DIR, model="padova/1994")


class TestOpenGrid:
    def test_sniffing_claims_the_family(self, grid_2000, grid_1994):
        assert grid_2000.identity.label == "padova/2000"
        assert len(grid_2000) == 5
        assert grid_1994.identity.label == "padova/1994"
        assert len(grid_1994) == 5  # four table5 blocks + one table1 block

    def test_summary_companion_not_read_as_a_grid_file(self, grid_2000):
        # only isochron.dat carries isochrones; isochsum.dat is the
        # companion the phase computation reads, not a second product
        assert len(grid_2000.sets) == 1

    def test_release_mismatch_fails_loudly(self):
        with pytest.raises(ValueError, match="release"):
            stellariso.open_grid(P1994_DIR, model="padova/2000")

    def test_mixed_release_directory_rejected(self):
        with pytest.raises(ValueError, match="cannot mix"):
            stellariso.open_grid(DATA)


class TestGridSelection:
    def test_axes(self, grid_2000, grid_1994):
        assert grid_2000.axis_values("log_age") == (7.8, 9.0, 10.0)
        assert grid_2000.axis_values("initial_feh") == pytest.approx(
            (-0.6766936096248666, 0.0)
        )
        assert grid_2000.axis_values("overshoot") == (0.0, 1.0)
        assert grid_1994.axis_values("initial_feh") == pytest.approx(
            (-1.6989700043360187, 0.0)
        )

    def test_exact_selection(self, grid_2000):
        iso = grid_2000.get_isochrone(
            method="exact", log_age=9.0, initial_feh=0.0, overshoot=1.0
        )
        assert iso.selection_info["method"] == "exact"

    def test_exact_selection_needs_multi_valued_axes_pinned(self, grid_2000):
        with pytest.raises(GridPointNotFoundError):
            grid_2000.get_isochrone(method="exact", log_age=9.0)

    def test_initial_feh_is_a_selection_coordinate(self, grid_2000):
        iso = grid_2000.get_isochrone(
            method="exact", log_age=9.0, initial_feh=0.0, overshoot=1.0
        )
        assert iso.native.metadata["z_values"] == (0.004, 0.019)

    def test_nearest_feh_snaps_and_warns(self, grid_1994):
        # the consumer grid's -0.5 has no exact point: the fixture's
        # [Fe/H] values are -1.70 and 0.0; nearest to -0.5 is 0.0
        with pytest.warns(NearestGridPointWarning):
            iso = grid_1994.get_isochrone(
                method="nearest", log_age=9.0, initial_feh=-0.5
            )
        assert iso.selection["initial_feh"] == pytest.approx(0.0)

    def test_nearest_age_snaps(self, grid_1994):
        with pytest.warns(NearestGridPointWarning):
            iso = grid_1994.get_isochrone(method="nearest", log_age=8.8, initial_feh=0.0)
        assert iso.selection["log_age"] == 9.0


class TestFacade:
    def test_construct_and_point_queries(self):
        iso = stellariso.construct(
            "padova/1994", paths=[P1994_DIR / "table1", P1994_DIR / "table5"]
        )
        logg = iso.get_logg(mass=1.0, log_age=9.0, initial_feh=0.0)
        assert 3.0 < logg < 5.0
        phase = iso.get_phase(mass=1.0, log_age=9.0, initial_feh=0.0)
        assert phase == "main_sequence"
        assert iso.last_record is not None
        assert iso.last_record.coordinate == "initial_mass"

    def test_construct_2000(self):
        iso = stellariso.construct("padova/2000", paths=[P2000_DIR / "isochron.dat"])
        assert iso.identity.label == "padova/2000"
        # the facade object is itself the grid: the multi-valued
        # overshoot axis must be pinned for exact selection
        with pytest.raises(GridPointNotFoundError):
            iso.get_isochrone(method="exact", log_age=9.0, initial_feh=0.0)

    def test_construct_release_validated(self):
        with pytest.raises(ValueError, match="release"):
            stellariso.construct("padova/2000", paths=[P1994_DIR / "table5"])

    def test_construct_requires_paths(self):
        with pytest.raises(ValueError, match="paths"):
            stellariso.construct("padova/1994")

    def test_describe(self):
        iso = stellariso.construct("padova/2000", paths=[P2000_DIR / "isochron.dat"])
        text = iso.describe()
        assert "PadovaIso" in text
        assert "padova/2000" in text
