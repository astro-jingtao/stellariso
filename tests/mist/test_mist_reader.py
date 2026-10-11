"""Tests for the MIST reader and backend against the real-data fixture."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from stellariso.core import ParameterRole
from stellariso.exceptions import DataIntegrityError, UnrecognizedFormatError
from stellariso.models.mist.backend import (
    mist_identity,
    mist_parameters,
    read_mist,
)
from stellariso.models.mist.reader import parse_mist_iso
from stellariso.native import NativeTable

FIXTURE = (
    Path(__file__).parent.parent / "data" / "mist" / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
)

# Golden values from the original file (see tests/data/mist/README.md).
GOLDEN_HEADER = {
    "mist_version": "1.2",
    "mesa_revision": "7503",
    "yinit": 0.2514,
    "zinit": 1.88066e-03,
    "feh": -1.00,
    "afe": 0.00,
    "vvcrit": 0.40,
    "n_isochrones": 2,
}
GOLDEN_BLOCKS = [(138, 79), (147, 79)]
GOLDEN_LOG_AGES = [9.0, 10.0]
GOLDEN_FIRST_ROW_EEP = 196


class TestReader:
    def test_fixture_exists(self):
        assert FIXTURE.exists()

    def test_header_facts(self):
        parsed = parse_mist_iso(FIXTURE)
        for key, value in GOLDEN_HEADER.items():
            assert parsed.facts[key] == value, key

    def test_native_columns_and_order(self):
        parsed = parse_mist_iso(FIXTURE)
        cols = parsed.native.columns
        assert cols[0] == "EEP"
        assert cols[1] == "log10_isochrone_age_yr"
        assert cols[2] == "initial_mass"
        assert "log_g" in cols and "phase" in cols
        assert len(cols) == 79

    def test_block_structure(self):
        parsed = parse_mist_iso(FIXTURE)
        assert len(parsed.blocks) == 2
        assert [(b.n_eeps, b.n_cols) for b in parsed.blocks] == GOLDEN_BLOCKS
        assert [b.n_rows for b in parsed.blocks] == [138, 147]
        assert len(parsed.native.table) == 138 + 147

    def test_header_lines_preserved(self):
        parsed = parse_mist_iso(FIXTURE)
        assert any("MIST version number" in ln for ln in parsed.native.header)
        assert any("Yinit" in ln for ln in parsed.native.header)

    def test_first_row_values(self):
        parsed = parse_mist_iso(FIXTURE)
        assert parsed.native["EEP"][0] == GOLDEN_FIRST_ROW_EEP
        # log_Teff of the first row, verbatim from the original file
        assert parsed.native["log_Teff"][0] == pytest.approx(3.5262686258142129)
        assert parsed.native["initial_mass"][0] == pytest.approx(0.1)

    def test_age_blocks_split_correctly(self):
        parsed = parse_mist_iso(FIXTURE)
        ages = []
        for b in parsed.blocks:
            col = parsed.native["log10_isochrone_age_yr"][b.row_start : b.row_stop]
            ages.append(float(np.round(np.unique(col)[0], 8)))
        assert ages == GOLDEN_LOG_AGES

    def test_corrupted_row_count_raises(self, tmp_path):
        lines = FIXTURE.read_text(encoding="ascii").splitlines()
        # inflate the declared EEP count of the first block
        for i, ln in enumerate(lines):
            if "number of EEPs, cols" in ln:
                lines[i] = ln.replace("=  138 ", "=  999 ")
                break
        bad = tmp_path / "bad.iso"
        bad.write_text("\n".join(lines), encoding="ascii")
        with pytest.raises(DataIntegrityError, match="999"):
            parse_mist_iso(bad)

    def test_not_a_mist_file_raises(self, tmp_path):
        bad = tmp_path / "not_mist.txt"
        bad.write_text("# some header\n1.0 2.0 3.0\n", encoding="ascii")
        with pytest.raises(UnrecognizedFormatError):
            parse_mist_iso(bad)


class TestBackend:
    def test_read_mist_set(self):
        s = read_mist(FIXTURE)
        assert s.identity.family == "mist"
        assert s.identity.release == "1.2"
        assert s.identity.physics_configuration == "vvcrit0.4"
        assert len(s) == 2
        assert s.keys() == GOLDEN_LOG_AGES
        assert s.indexer == "log_age"

    def test_identity_label(self):
        s = read_mist(FIXTURE)
        assert s.identity.label == "mist/1.2/vvcrit0.4"

    def test_selection_pins_axes(self):
        iso = read_mist(FIXTURE)[1]
        assert iso.selection["log_age"] == 9.5 or iso.selection["log_age"] == 10.0
        assert iso.parameter_value("log_age") == iso.selection["log_age"]
        assert iso.parameter_value("initial_feh") == -1.00
        assert iso.parameter_value("initial_rotation") == 0.40
        assert iso.parameter_value("alpha_fe") == 0.00

    def test_fixed_native_parameters(self):
        s = read_mist(FIXTURE)
        assert s.parameter("initial_z").value == pytest.approx(1.88066e-03)
        assert s.parameter("initial_helium").value == pytest.approx(0.2514)

    def test_implicit_parameters_present(self):
        s = read_mist(FIXTURE)
        spec = s.parameter("mixing_length")
        assert spec.role is ParameterRole.IMPLICIT
        assert spec.status == "not_reported"

    def test_axis_roles(self):
        s = read_mist(FIXTURE)
        assert s.parameter("log_age").role is ParameterRole.AXIS
        assert s.parameter("log_age").values == (9.0, 10.0)
        assert s.parameter("initial_rotation").values == (0.0, 0.4)
        assert s.parameter("initial_feh").values == (-1.0,)

    def test_provenance_carries_references(self):
        s = read_mist(FIXTURE)
        cites = " ".join(r.citation for r in s.provenance.scientific_references)
        assert "Choi" in cites and "Dotter" in cites

    def test_block_native_slices_share_columns(self):
        s = read_mist(FIXTURE)
        for iso in s:
            assert isinstance(iso.native, NativeTable)
            assert len(iso.native.columns) == 79
            assert len(iso) == iso.native.block_metadata[0]["n_eeps"]
