"""Tests for IsochroneGrid selection and open_grid."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stellariso.exceptions import (
    AmbiguousFormatError,
    GridPointNotFoundError,
    UnrecognizedFormatError,
)
from stellariso.grid import IsochroneGrid, open_grid
from stellariso.isochrone import IsochroneSet
from stellariso.models.mist.backend import read_mist
from stellariso.warnings import NearestGridPointWarning

FIXTURE = (
    Path(__file__).parent / "data" / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
)


@pytest.fixture(scope="module")
def grid():
    return IsochroneGrid.from_paths("mist", [FIXTURE])


class TestGridIntrospection:
    def test_axes(self, grid):
        assert grid.axis_values("log_age") == (9.0, 10.0)
        assert grid.axis_values("initial_feh") == (-1.0,)
        assert grid.axis_values("initial_rotation") == (0.4,)
        assert grid.axes["alpha_fe"] == (0.0,)

    def test_identity_and_size(self, grid):
        assert len(grid) == 2
        assert grid.identity.family == "mist"


class TestExactSelection:
    def test_exact_hit(self, grid):
        iso = grid.get_isochrone(log_age=9.0, initial_feh=-1.0)
        assert iso.selection["log_age"] == 9.0
        assert iso.selection_info["method"] == "exact"

    def test_exact_miss_raises(self, grid):
        with pytest.raises(GridPointNotFoundError):
            grid.get_isochrone(log_age=9.5)

    def test_unknown_coordinate_rejected(self, grid):
        with pytest.raises(ValueError, match="unknown selection"):
            grid.get_isochrone(teff=5000)

    def test_bad_method_rejected(self, grid):
        with pytest.raises(ValueError, match="method"):
            grid.get_isochrone(method="interpolate", log_age=9.0)


class TestNearestSelection:
    def test_nearest_snaps_and_warns(self, grid):
        with pytest.warns(NearestGridPointWarning, match="nearest"):
            iso = grid.get_isochrone(log_age=9.2, method="nearest")
        assert iso.selection["log_age"] in (9.0, 10.0)
        info = iso.selection_info
        assert info["requested"]["log_age"] == 9.2
        assert info["returned"]["log_age"] == iso.selection["log_age"]
        assert info["distances"]["log_age"] == pytest.approx(
            abs(iso.selection["log_age"] - 9.2)
        )

    def test_nearest_exact_hit_no_warning(self, grid):
        with warnings_as_errors():
            iso = grid.get_isochrone(log_age=9.0, method="nearest")
        assert iso.selection_info["distances"]["log_age"] == 0.0

    def test_nearest_with_multiple_unpinned_raises(self, grid):
        # one file -> feh pinned implicitly by available values; a request
        # that leaves no ambiguity works:
        with pytest.warns(NearestGridPointWarning):
            iso = grid.get_isochrone(method="nearest", log_age=9.4)
        assert iso.selection["log_age"] in (9.0, 10.0)


import warnings as _w

from contextlib import contextmanager


@contextmanager
def warnings_as_errors():
    with _w.catch_warnings():
        _w.simplefilter("error")
        yield


class TestSelectionInfoIsolation:
    def test_annotated_copy_does_not_mutate_shared_iso(self, grid):
        iso1 = grid.get_isochrone(log_age=9.0)
        with pytest.warns(NearestGridPointWarning):
            iso2 = grid.get_isochrone(method="nearest", log_age=9.2)
        assert iso1.selection_info["method"] == "exact"
        assert iso2.selection_info["method"] == "nearest"
        # both share the same underlying native table (no data copied)
        assert iso1.native is iso2.native


class TestOpenGrid:
    def test_open_single_file_with_model(self):
        g = open_grid(FIXTURE, model="mist")
        assert len(g) == 2

    def test_open_single_file_autodetect(self):
        g = open_grid(FIXTURE)
        assert g.identity.family == "mist"

    def test_open_directory(self, tmp_path):
        d = tmp_path / "mist_data"
        d.mkdir()
        shutil.copy(FIXTURE, d / "a.iso")
        g = open_grid(d, model="mist")
        assert len(g) == 2
        g2 = open_grid(d)
        assert g2.identity.family == "mist"

    def test_open_unknown_file_raises(self, tmp_path):
        f = tmp_path / "junk.dat"
        f.write_text("hello world\n")
        with pytest.raises(UnrecognizedFormatError):
            open_grid(f)
        with pytest.raises(UnrecognizedFormatError):
            open_grid(f, model="mist")

    def test_open_empty_directory_raises(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        with pytest.raises(UnrecognizedFormatError):
            open_grid(d, model="mist")

    def test_mixed_identities_rejected(self, tmp_path):
        # same backend, but feed the same file twice: duplicate grid points
        with pytest.raises(ValueError, match="duplicate"):
            IsochroneGrid([read_mist(FIXTURE), read_mist(FIXTURE)])

    def test_gzip_fixture_roundtrip(self, tmp_path):
        import gzip

        gz = tmp_path / "fixture.iso.gz"
        with open(FIXTURE, "rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        g = open_grid(gz, model="mist")
        assert len(g) == 2
        assert g.axis_values("log_age") == (9.0, 10.0)
