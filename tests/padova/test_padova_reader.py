"""Reader tests for the two padova archive layouts."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest

from stellariso.exceptions import DataIntegrityError, UnrecognizedFormatError
from stellariso.models.padova.reader import (
    TABLE_COMPOSITIONS_1994,
    parse_padova1994,
    parse_padova2000,
    parse_padova2000_summary,
    recognize_padova,
    sniff_layout,
)

DATA = Path(__file__).parent.parent / "data" / "padova"
ISOCHRON_2000 = DATA / "p2000" / "isochron.dat"
ISOSCHSUM_2000 = DATA / "p2000" / "isochsum.dat"
TABLE5_1994 = DATA / "p1994" / "table5"
MIST_FIXTURE = (
    Path(__file__).parent.parent / "data" / "mist"
    / "MIST_v1.2_feh_m1.00_afe_p0.0_vvcrit0.4_fixture.iso"
)


@pytest.fixture(scope="module")
def p2000():
    return parse_padova2000(ISOCHRON_2000)


@pytest.fixture(scope="module")
def p1994():
    return parse_padova1994(TABLE5_1994)


class TestParsePadova2000:
    def test_blocks_and_facts(self, p2000):
        assert p2000.facts["release"] == "2000"
        assert p2000.facts["n_isochrones"] == 5
        assert p2000.facts["z_values"] == (0.004, 0.019)
        assert p2000.facts["overshoot_values"] == (0, 1)
        assert len(p2000.blocks) == 5

    def test_block_grid_points(self, p2000):
        keys = {(b.overshoot, b.z, b.log_age) for b in p2000.blocks}
        assert keys == {
            (1, 0.019, 9.0),
            (1, 0.019, 10.0),
            (0, 0.019, 9.0),
            (1, 0.004, 9.0),
            (1, 0.019, 7.8),
        }

    def test_native_columns_verbatim(self, p2000):
        assert p2000.native.columns == [
            "Overshoot", "Z", "age", "log(age)", "Mini", "Mact", "logL",
            "logTeff", "logg", "Mbol", "UMAG", "BMAG", "VMAG", "RMAG",
            "IMAG", "JMAG", "HMAG", "KMAG", "FLUM",
        ]
        # first data row of the archive, read back at the ReadMe offsets
        row = p2000.native.table[0]
        assert row["Overshoot"] == 1
        assert row["Mini"] == pytest.approx(0.15000001)
        assert row["FLUM"] == pytest.approx(-9.59274740)

    def test_row_counts_match_blocks(self, p2000):
        total = sum(b.row_stop - b.row_start for b in p2000.blocks)
        assert total == len(p2000.native.table)

    def test_rejects_other_layouts(self):
        with pytest.raises(UnrecognizedFormatError):
            parse_padova2000(TABLE5_1994)

    def test_corrupt_field_is_a_data_error(self, tmp_path):
        bad = tmp_path / "isochron.dat"
        lines = ISOCHRON_2000.read_text(encoding="ascii").splitlines()
        # keep the line length (the layout sniffer must pass) and break
        # the logg field, which the sniffer does not read
        corrupt = lines[0][:59] + "xxxxxxx" + lines[0][66:]
        bad.write_text(corrupt + "\n", encoding="ascii")
        with pytest.raises(DataIntegrityError):
            parse_padova2000(bad)


class TestParsePadova2000Summary:
    def test_boundary_anchors_only(self):
        anchors = parse_padova2000_summary(ISOSCHSUM_2000)
        assert len(anchors) == 5
        solar = anchors[(1, 0.019, 9.0)]
        # the interior markers (Te-m, Te-M, L-M, L-m) never appear
        assert set(solar) == {"TO", "RGBb", "RGBt", "BHeb", "EHeb", "1TP"}
        # masses in the source's own characteristic-point order
        values = [solar[k] for k in ("TO", "RGBb", "RGBt", "BHeb", "EHeb", "1TP")]
        assert values == sorted(values)
        assert solar["TO"] == pytest.approx(1.7933)

    def test_young_isochrone_has_no_tp_agb_anchor(self):
        anchors = parse_padova2000_summary(ISOSCHSUM_2000)
        assert "1TP" not in anchors[(1, 0.019, 7.8)]
        assert "EHeb" in anchors[(1, 0.019, 7.8)]


class TestParsePadova1994:
    def test_composition_from_canonical_name(self, p1994):
        assert p1994.facts["release"] == "1994"
        assert p1994.facts["table"] == "table5"
        assert p1994.facts["initial_z"] == 0.02
        assert p1994.facts["initial_helium"] == 0.28
        assert p1994.facts["n_isochrones"] == 4

    def test_block_ages_in_file_order(self, p1994):
        # the archive lists isochrones oldest first; the reader preserves
        # the file's order
        assert [b.log_age for b in p1994.blocks] == [10.0, 9.0, 7.0, 6.7]

    def test_native_columns_verbatim(self, p1994):
        assert p1994.native.columns[:4] == ["log(Age)", "M", "log(Teff)", "Mbol"]
        assert p1994.native.columns[-2:] == ["FLUM", "Mwind"]

    def test_all_tables_have_documented_compositions(self):
        assert set(TABLE_COMPOSITIONS_1994) == {f"table{i}" for i in range(1, 7)}
        assert TABLE_COMPOSITIONS_1994["table1"] == (0.0004, 0.23)
        assert TABLE_COMPOSITIONS_1994["table6"] == (0.05, 0.352)

    def test_canonical_name_required(self, tmp_path):
        renamed = tmp_path / "z02_table.dat"
        shutil.copy(TABLE5_1994, renamed)
        with pytest.raises(UnrecognizedFormatError, match="canonical"):
            parse_padova1994(renamed)

    def test_rejects_other_layouts(self):
        with pytest.raises(UnrecognizedFormatError):
            parse_padova1994(ISOCHRON_2000)


class TestGzipInputs:
    def test_gz_roundtrip_1994(self, tmp_path):
        gz = tmp_path / "table5.gz"
        with open(TABLE5_1994, "rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        plain = parse_padova1994(TABLE5_1994)
        inflated = parse_padova1994(gz)
        assert plain.native == inflated.native

    def test_gz_not_claimed_when_plain_twin_exists(self, tmp_path):
        shutil.copy(TABLE5_1994, tmp_path / "table5")
        gz = tmp_path / "table5.gz"
        with open(TABLE5_1994, "rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        assert recognize_padova(gz) is False
        assert recognize_padova(tmp_path / "table5") is True

    def test_lone_gz_is_claimed(self, tmp_path):
        gz = tmp_path / "table5.gz"
        with open(TABLE5_1994, "rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        assert recognize_padova(gz) is True


class TestSniffing:
    def test_sniff_classifies_both_layouts(self, p2000, p1994):
        first_2000 = open(ISOCHRON_2000, encoding="ascii").readline().rstrip("\n")
        first_1994 = open(TABLE5_1994, encoding="ascii").readline().rstrip("\n")
        assert sniff_layout([first_2000]) == "2000"
        assert sniff_layout([first_1994]) == "1994"

    def test_other_files_not_recognized(self):
        assert sniff_layout(["# MIST version number  = 1.2"]) is None
        assert recognize_padova(MIST_FIXTURE) is False
