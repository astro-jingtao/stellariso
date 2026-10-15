"""Offline tests for the PARSEC form-product acquisition blueprint.

The blueprint is pure design data (no network): these tests pin its grid
arithmetic, its run-4 backward compatibility (existing product labels
and payload overrides must reproduce exactly), and the validity of every
designed payload against the request layer's own validation.
"""

from __future__ import annotations

import warnings

import pytest

from stellariso.models.parsec.blueprint import (
    LINEAR_AGE_GRID,
    LOG_AGE_GRID,
    TRACK_SETS,
    Cell,
    all_cells,
    canonical_fields,
    cells,
    expected_linear_ages,
    expected_log_ages,
    mh_grid,
    mh_label,
    z_to_mh,
)
from stellariso.models.parsec.cmd_form import (
    DEFAULT_FIELDS,
    CmdFieldSet,
    CmdFormOptionWarning,
)


class TestMetallicityConversion:
    def test_solar_zero_point_matches_faq(self):
        # The FAQ states [M/H]=0 corresponds to Z=0.014711.
        assert round(z_to_mh(0.014711), 4) == 0.0

    def test_colibri_z_window_edges(self):
        # S35/S07: 0.0005 <= Z <= 0.03, converted via the enrichment law.
        assert round(z_to_mh(0.0005), 4) == -1.4921
        assert round(z_to_mh(0.03), 4) == 0.3363


class TestCompositionGrid:
    def test_stated_windows_on_grid(self):
        assert mh_grid(-2.2, 0.5) == tuple(round(-2.2 + 0.1 * k, 10) for k in range(28))
        assert len(mh_grid(-1.5, 0.6)) == 22

    def test_off_grid_edges_supplemented(self):
        grid = mh_grid(-2.19, 0.34)
        assert -2.19 in grid and 0.34 in grid
        assert len(grid) == 27  # 25 interior 0.1 steps + both exact edges

    def test_converted_window_edges_supplemented(self):
        grid = mh_grid(-1.4921, 0.3363)
        assert -1.4921 in grid and 0.3363 in grid
        assert len(grid) == 20  # 18 interior 0.1 steps + both exact edges

    def test_labels_run4_compatible(self):
        assert mh_label(0.0) == "mh_p0.0"
        assert mh_label(-2.2) == "mh_m2.2"
        assert mh_label(0.5) == "mh_p0.5"
        assert mh_label(-1.0) == "mh_m1.0"
        assert mh_label(2.0) == "mh_p2.0"

    def test_labels_boundary_supplements(self):
        assert mh_label(-2.19) == "mh_m2.19"
        assert mh_label(0.34) == "mh_p0.34"
        assert mh_label(-1.4921) == "mh_m1.4921"


class TestGridDeclarations:
    def test_age_grids(self):
        assert LOG_AGE_GRID == ("6.6", "10.13", "0.02")
        assert LINEAR_AGE_GRID == ("0.0", "4.0e6", "1.0e5")
        assert expected_log_ages() == 177  # 6.6 .. 10.12; 10.13 off-grid
        assert expected_linear_ages() == 41  # 0 .. 4.0 Myr by 0.1 Myr

    def test_omega_grid(self):
        v2 = cells("v2.0")
        omegas = sorted({c.omega for c in v2})
        assert omegas == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99]

    def test_canonical_fields_are_the_request_baseline(self):
        assert canonical_fields() == DEFAULT_FIELDS


class TestCellEnumeration:
    @pytest.mark.parametrize(
        ("key", "n"),
        [
            ("v1.2S_COLIBRI_web", 28),  # 28 [M/H] x 1 omega
            ("v2.0", 297),  # 27 [M/H] x 11 omega
            ("v1.2S_COLIBRI_S35", 20),
            ("v1.2S_COLIBRI_S07", 20),
            ("v1.2S_COLIBRI_PR16", 28),
            ("v1.2S_no_colibri", 28),
            ("v1.1", 28),
            ("v1.0", 22),
        ],
    )
    def test_full_extent_counts(self, key, n):
        assert len(cells(key)) == n

    def test_full_blueprint_total(self):
        assert sum(1 for _ in all_cells()) == 471

    def test_cell_labels(self):
        ts = TRACK_SETS["v1.2S_COLIBRI_web"]
        assert Cell(set=ts, mh=0.0, omega=0.0).label == "mh_p0.0"
        assert Cell(set=ts, mh=-2.2, omega=0.0).relative_dir == (
            "v1.2S_COLIBRI_web/mh_m2.2"
        )
        v2 = TRACK_SETS["v2.0"]
        assert Cell(set=v2, mh=0.3, omega=0.4).label == "mh_p0.3_w0.40"
        assert Cell(set=v2, mh=-2.19, omega=0.99).label == "mh_m2.19_w0.99"
        v10 = TRACK_SETS["v1.0"]
        assert Cell(set=v10, mh=0.6, omega=0.0).label == "v1.0_mh_p0.6"

    def test_sparse_slices(self):
        total = 0
        for key, ts in TRACK_SETS.items():
            if ts.tier != "secondary":
                with pytest.raises(ValueError):
                    cells(key, sparse=True)
                continue
            sparse = cells(key, sparse=True)
            full = cells(key)
            assert set(c.label for c in sparse) <= set(c.label for c in full)
            assert {ts.mh_low, ts.mh_high} <= {c.mh for c in sparse}
            assert {-1.0, 0.0, 0.3} <= {c.mh for c in sparse}
            total += len(sparse)
        assert total == 30  # 5 compositions x 6 secondary sets

    def test_sparse_slice_boundaries_off_grid(self):
        s35 = cells("v1.2S_COLIBRI_S35", sparse=True)
        assert sorted(c.mh for c in s35) == [-1.4921, -1.0, 0.0, 0.3, 0.3363]


class TestPayloads:
    def test_log_fields_reproduce_run4_payload(self):
        # The v2.0 mh_m0.1 product archived exactly these overrides on
        # top of DEFAULT_FIELDS (output.dat.record.json, 2026-10-14).
        cell = Cell(set=TRACK_SETS["v2.0"], mh=-0.1, omega=0.0)
        assert cell.log_fields() == {
            "track_parsec": "parsec_CAF09_v2.0",
            "track_colibri": "no",
            "track_omegai": "0.00",
            "photsys_version": "YBCnewVega",
            "photsys_file": "YBC_tab_mag_odfnew/tab_mag_ubvrijhk.dat",
            "isoc_ismetlog": "1",
            "isoc_metlow": "-0.1",
            "isoc_metupp": "-0.1",
            "isoc_dmet": "0",
            "isoc_isagelog": "1",
            "isoc_lagelow": "6.6",
            "isoc_lageupp": "10.13",
            "isoc_dlage": "0.02",
        }

    def test_linear_fields(self):
        cell = Cell(set=TRACK_SETS["v1.2S_COLIBRI_web"], mh=-2.2, omega=0.0)
        fields = cell.linear_fields()
        assert fields["isoc_isagelog"] == "0"
        assert fields["isoc_agelow"] == "0.0"
        assert fields["isoc_ageupp"] == "4.0e6"
        assert fields["isoc_dage"] == "1.0e5"
        assert fields["isoc_metlow"] == "-2.2"

    def test_every_designed_payload_validates(self):
        # Every cell of the full blueprint, both age grids, must pass the
        # request layer's closed-set/bounds validation without a single
        # advisory warning (an advisory here would mean a designed cell
        # the form would ignore part of).
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for cell in all_cells():
                CmdFieldSet.from_overrides(**cell.log_fields())
                CmdFieldSet.from_overrides(**cell.linear_fields())

    def test_omega_warning_stays_silent_for_designed_cells(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", CmdFormOptionWarning)
            for cell in cells("v2.0"):
                CmdFieldSet.from_overrides(**cell.log_fields())
