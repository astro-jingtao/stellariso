"""Offline tests for the PARSEC form-product acquisition blueprint.

The blueprint is pure design data (no network): these tests pin its grid
arithmetic, its axis applicability, its run-4 backward compatibility
(existing product labels and payload overrides must reproduce exactly),
the full-coverage counts of the redesigned axis space, and the validity
of designed payloads against the request layer's own validation.
"""

from __future__ import annotations

import warnings

import pytest

from stellariso.models.parsec.blueprint import (
    CANONICAL_DUST_C,
    CANONICAL_DUST_M,
    CANONICAL_ETA,
    CANONICAL_LPV,
    DUST_C_VALUES,
    DUST_M_VALUES,
    ETA_VALUES,
    FETCH_ETA_VALUES,
    LINEAR_AGE_GRID,
    LOG_AGE_GRID,
    LPV_VALUES,
    TRACK_SETS,
    Cell,
    all_cells,
    canonical_fields,
    cells,
    fetch_cells,
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

    def test_axis_values_match_the_form(self):
        assert ETA_VALUES == (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
        assert FETCH_ETA_VALUES == (0.0, 0.2, 0.4)
        assert DUST_M_VALUES == ("nodustM", "sil", "AlOx", "dpmod60alox40", "dpmod")
        assert DUST_C_VALUES == ("nodustC", "gra", "AMC", "AMCSIC15")
        assert LPV_VALUES == ("1", "2", "3", "4")

    def test_canonical_axes_are_the_request_baseline(self):
        assert CANONICAL_ETA == float(DEFAULT_FIELDS["eta_reimers"])
        assert CANONICAL_DUST_M == DEFAULT_FIELDS["dust_sourceM"]
        assert CANONICAL_DUST_C == DEFAULT_FIELDS["dust_sourceC"]
        assert CANONICAL_LPV == DEFAULT_FIELDS["kind_LPV"]


class TestAxisApplicability:
    def test_v20_has_no_eta_axis(self):
        # No Reimers echo in archived v2.0 headers; the form states eta is
        # not applied for v2.0 tracks.
        ts = TRACK_SETS["v2.0"]
        assert ts.eta_applies is False
        assert ts.eta_values == (CANONICAL_ETA,)

    def test_v20_keeps_dust_and_lpv_axes(self):
        # Archived v2.0 headers echo the dust and LPV switches and the
        # column line carries period0-4/pmode.
        ts = TRACK_SETS["v2.0"]
        assert ts.dust_m_values == DUST_M_VALUES
        assert ts.lpv_values == LPV_VALUES

    @pytest.mark.parametrize(
        "key", ["v1.2S_no_colibri", "v1.1", "v1.0"],
    )
    def test_no_tp_agb_sets_collapse_dust_and_lpv(self, key):
        # 17-column outputs without period or TP-AGB columns: dust and
        # LPV have nothing to act on, wherever eta does act.
        ts = TRACK_SETS[key]
        assert ts.eta_applies is True
        assert ts.dust_applies is False
        assert ts.lpv_applies is False
        assert ts.dust_m_values == (CANONICAL_DUST_M,)
        assert ts.dust_c_values == (CANONICAL_DUST_C,)
        assert ts.lpv_values == (CANONICAL_LPV,)

    @pytest.mark.parametrize(
        "key", ["v1.2S_COLIBRI_web", "v1.2S_COLIBRI_S35", "v1.2S_COLIBRI_S07",
                "v1.2S_COLIBRI_PR16"],
    )
    def test_colibri_sets_carry_every_axis(self, key):
        ts = TRACK_SETS[key]
        assert ts.eta_applies and ts.dust_applies and ts.lpv_applies


class TestCellEnumeration:
    @pytest.mark.parametrize(
        ("key", "n"),
        [
            ("v1.2S_COLIBRI_web", 13440),  # 28 [M/H] x 6 eta x 20 dust x 4 lpv
            ("v2.0", 23760),  # 27 [M/H] x 11 omega x 20 dust x 4 lpv (eta inert)
            ("v1.2S_COLIBRI_S35", 9600),  # 20 x 6 x 20 x 4
            ("v1.2S_COLIBRI_S07", 9600),
            ("v1.2S_COLIBRI_PR16", 13440),
            ("v1.2S_no_colibri", 168),  # 28 x 6 eta (dust/lpv inert)
            ("v1.1", 168),
            ("v1.0", 132),  # 22 x 6 eta
        ],
    )
    def test_full_extent_counts(self, key, n):
        assert len(cells(key)) == n

    def test_full_blueprint_total(self):
        assert sum(1 for _ in all_cells()) == 70308

    def test_cell_labels_canonical_are_run4_labels(self):
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

    def test_cell_labels_non_canonical_axes(self):
        ts = TRACK_SETS["v1.2S_COLIBRI_web"]
        assert Cell(set=ts, mh=0.0, omega=0.0, eta=0.0).label == "mh_p0.0_e0.0"
        assert Cell(set=ts, mh=0.0, omega=0.0, eta=0.5).label == "mh_p0.0_e0.5"
        assert (
            Cell(set=ts, mh=-1.0, omega=0.0, dust_m="nodustM", dust_c="nodustC").label
            == "mh_m1.0_dMnodustM_dCnodustC"
        )
        assert Cell(set=ts, mh=0.0, omega=0.0, lpv="1").label == "mh_p0.0_lpv1"
        v2 = TRACK_SETS["v2.0"]
        assert (
            Cell(set=v2, mh=0.3, omega=0.4, dust_m="sil", lpv="2").label
            == "mh_p0.3_w0.40_dMsil_lpv2"
        )
        # inert axes never render, canonical or not
        assert Cell(set=v2, mh=0.3, omega=0.0, eta=0.4).label == "mh_p0.3"

    def test_labels_unique_within_each_set(self):
        # Labels identify a cell inside its set's directory; across sets
        # the set key (the parent directory) disambiguates.
        for key, ts in TRACK_SETS.items():
            seen = set()
            for cell in cells(ts):
                assert cell.label not in seen, (key, cell.label)
                seen.add(cell.label)

    def test_sparse_slices(self):
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

    def test_sparse_slice_boundaries_off_grid(self):
        s35 = cells("v1.2S_COLIBRI_S35", sparse=True)
        assert sorted({c.mh for c in s35}) == [-1.4921, -1.0, 0.0, 0.3, 0.3363]


class TestFetchStage:
    def test_fetch_stage_is_a_design_subset(self):
        for key, ts in TRACK_SETS.items():
            designed = {c.label for c in cells(ts)}
            for fetched in (fetch_cells(ts), fetch_cells(ts, sparse=False)):
                assert {c.label for c in fetched} <= designed

    @pytest.mark.parametrize(
        ("key", "n"),
        [
            ("v1.2S_COLIBRI_web", 84),  # 28 [M/H] x 3 fetch eta
            ("v2.0", 297),  # eta inert: 27 x 11 omega, canonical eta only
            ("v1.2S_COLIBRI_S35", 15),  # 5 sparse [M/H] x 3 fetch eta
            ("v1.2S_COLIBRI_S07", 15),
            ("v1.2S_COLIBRI_PR16", 15),
            ("v1.2S_no_colibri", 15),
            ("v1.1", 15),
            ("v1.0", 15),
        ],
    )
    def test_fetch_stage_counts(self, key, n):
        assert len(fetch_cells(key)) == n

    def test_fetch_stage_total(self):
        total = sum(len(fetch_cells(ts)) for ts in TRACK_SETS.values())
        assert total == 471

    def test_fetch_stage_axes(self):
        web = fetch_cells("v1.2S_COLIBRI_web")
        assert sorted({c.eta for c in web}) == [0.0, 0.2, 0.4]
        assert {c.dust_m for c in web} == {CANONICAL_DUST_M}
        assert {c.lpv for c in web} == {CANONICAL_LPV}

    def test_secondary_full_extent_completion_stage(self):
        # sparse=False on a secondary set is its later completion stage:
        # every designed [M/H] at the fetch-stage axis values.
        assert len(fetch_cells("v1.2S_COLIBRI_S35", sparse=False)) == 60

    def test_sparse_fetch_rejected_for_primary(self):
        with pytest.raises(ValueError):
            fetch_cells("v1.2S_COLIBRI_web", sparse=True)


class TestPayloads:
    def test_log_fields_reproduce_run4_payload(self):
        # The v2.0 mh_m0.1 product archived exactly these overrides on
        # top of DEFAULT_FIELDS (output.dat.record.json, 2026-10-14);
        # the canonical axis values the record carries are the ones the
        # canonical cell emits.
        cell = Cell(set=TRACK_SETS["v2.0"], mh=-0.1, omega=0.0)
        assert cell.log_fields() == {
            "track_parsec": "parsec_CAF09_v2.0",
            "track_colibri": "no",
            "track_omegai": "0.00",
            "eta_reimers": "0.2",
            "dust_sourceM": "dpmod60alox40",
            "dust_sourceC": "AMCSIC15",
            "kind_LPV": "4",
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

    def test_axis_values_reach_the_payload(self):
        ts = TRACK_SETS["v1.2S_COLIBRI_web"]
        cell = Cell(set=ts, mh=0.0, omega=0.0, eta=0.5,
                    dust_m="AlOx", dust_c="gra", lpv="1")
        fields = cell.log_fields()
        assert fields["eta_reimers"] == "0.5"
        assert fields["dust_sourceM"] == "AlOx"
        assert fields["dust_sourceC"] == "gra"
        assert fields["kind_LPV"] == "1"

    @pytest.mark.parametrize("which", ["log", "linear"])
    def test_every_axis_extreme_payload_validates(self, which):
        # Every set at one [M/H], every value of every applicable axis,
        # both axis extremes jointly: a bounded sample of the full design
        # that still touches each closed value set end to end (an
        # advisory here would mean a designed cell the form would ignore
        # part of).
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for ts in TRACK_SETS.values():
                mh = ts.sparse_mh_values[0]
                for eta in ts.eta_values:
                    for dust_m in (ts.dust_m_values[0], ts.dust_m_values[-1]):
                        for dust_c in (ts.dust_c_values[0], ts.dust_c_values[-1]):
                            for lpv in ts.lpv_values:
                                cell = Cell(set=ts, mh=mh, omega=0.0, eta=eta,
                                            dust_m=dust_m, dust_c=dust_c, lpv=lpv)
                                CmdFieldSet.from_overrides(
                                    **(cell.log_fields() if which == "log"
                                       else cell.linear_fields())
                                )

    def test_omega_warning_stays_silent_for_designed_cells(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", CmdFormOptionWarning)
            for cell in fetch_cells("v2.0"):
                CmdFieldSet.from_overrides(**cell.log_fields())
