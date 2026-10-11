"""PARSEC v1.2S track reader and local isochrone synthesis, on real data."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from stellariso.core import FieldOrigin, ParameterRole
from stellariso.exceptions import DataIntegrityError, UnrecognizedFormatError
from stellariso.facade import ParsecIso
from stellariso.models.parsec.tracks import (
    ParsecTrackSet,
    parse_parsec_track_file,
    parse_parsec_tracks,
    recognize_parsec_track_file,
)
from stellariso.synthesis import synthesize_isochrone, synthesize_isochrones
from stellariso.warnings import (
    PhaseMappingWarning,
    SynthesizedProductWarning,
)

FIXTURE = Path(__file__).parent.parent / "data" / "parsec" / "tracks_v1p2S_Z0.0001Y0.249_fixture"

# golden values read off the fixture's M000.800.DAT at the model with
# AGE = 1.09509790899e9 yr (a main-sequence point, PHASE = 5.099)
GOLDEN_AGE_YR = 1.09509790899e9
GOLDEN = {
    "log_luminosity": -0.16056,
    "log_effective_temperature": 3.79913,
    "log_radius_cm": 10.68756,  # the file's LOG_R column, log10(cm)
    "current_mass": 0.80000,
    "phase_code": 5.0,
}


@pytest.fixture(scope="module")
def track_set() -> ParsecTrackSet:
    return parse_parsec_tracks(FIXTURE)


class TestTrackReader:
    def test_set_structure(self, track_set):
        assert len(track_set.tracks) == 3
        assert [t.initial_mass for t in track_set] == [0.6, 0.8, 1.0]
        assert len(track_set.hb_tracks) == 1
        assert track_set.hb_tracks[0].kind == "hb"
        assert len(track_set.discarded) == 1
        assert "ADD" in track_set.discarded[0]

    def test_identity_and_parameters(self, track_set):
        identity = track_set.identity
        assert identity.family == "parsec"
        assert identity.release == "v1.2S"
        assert identity.product == "stellar_tracks"
        params = {p.name: p for p in track_set.parameters}
        assert params["initial_mass"].role is ParameterRole.AXIS
        assert params["initial_mass"].values == (0.6, 0.8, 1.0)
        assert params["initial_z"].value == pytest.approx(0.0001)
        assert params["initial_helium"].value == pytest.approx(0.249)
        assert params["initial_rotation"].role is ParameterRole.NOT_APPLICABLE

    def test_single_file_reader(self, track_set):
        path = (
            FIXTURE / "Z0.0001Y0.249"
            / "Z0.0001Y0.249OUTA1.74_F7_M000.800.DAT"
        )
        assert recognize_parsec_track_file(path)
        track = parse_parsec_track_file(path)
        assert track.initial_mass == pytest.approx(0.8)
        assert track.kind == "standard"

    def test_native_layer_is_verbatim(self, track_set):
        track = track_set.tracks[1]
        assert "LOG_R" in track.native
        assert track.native.header[0].split()[0] == "MODELL"

    def test_bad_source_rejected(self, tmp_path):
        with pytest.raises(UnrecognizedFormatError):
            parse_parsec_tracks(tmp_path)


class TestTrackUnifiedView:
    def test_field_mappings(self, track_set):
        view = track_set.tracks[1].unified
        assert view["log_luminosity"][0] == pytest.approx(
            float(track_set.tracks[1].native["LOG_L"][0])
        )
        # log_radius shifts the file's LOG_R (log cm) into log10(R/Rsun)
        shifted = view["log_radius"][0]
        assert shifted == pytest.approx(
            float(track_set.tracks[1].native["LOG_R"][0]) - math.log10(6.957e10)
        )
        spec = view.field_spec("log_radius")
        assert spec.origin is FieldOrigin.TRANSFORMED_NATIVE
        assert spec.native_unit == "dex(cm)"

    def test_initial_mass_is_file_metadata(self, track_set):
        view = track_set.tracks[1].unified
        assert set(np.atleast_1d(view["initial_mass"])) == {0.8}
        assert view.field_spec("initial_mass").origin is FieldOrigin.FILE_METADATA

    def test_surface_gravity_closure(self, track_set):
        # g = G M / R^2 must close against the file's own columns
        track = track_set.tracks[1]
        log_g = track.unified["log_surface_gravity"]
        mass = np.asarray(track.native["MASS"], dtype=float) * 1.98847e33
        r_cm = 10.0 ** np.asarray(track.native["LOG_R"], dtype=float)
        expected = np.log10(6.67430e-8 * mass / r_cm**2)
        np.testing.assert_allclose(log_g, expected, rtol=0, atol=1e-12)

    def test_phase_mapping_on_real_codes(self, track_set):
        track = track_set.tracks[1]  # 0.8 Msun: PMS .. He ignition
        phases = track.unified["phase"]
        codes = np.floor(
            np.asarray(track.native["PHASE"], dtype=float) + 1e-9
        ).astype(int)
        assert phases[0] == "pre_main_sequence"  # code 1
        assert codes[-1] == 11  # track ends at core helium ignition
        assert phases[-1] == "core_helium_burning"
        # main-sequence codes (5, 6) present in the middle of the track
        ms = [p for c, p in zip(codes, phases) if c in (5, 6)]
        assert ms and set(ms) == {"main_sequence"}

    def test_hb_uses_its_own_mapping(self, track_set):
        hb = track_set.hb_tracks[0]
        phases = hb.unified["phase"]
        codes = np.floor(
            np.asarray(hb.native["PHASE"], dtype=float) + 1e-9
        ).astype(int)
        first = phases[0]
        assert first == "core_helium_burning"  # HB code 1, not PMS
        assert not any(p == "pre_main_sequence" for p in phases)
        assert codes[0] == 1


class TestSynthesis:
    def test_synthesis_at_one_gyr(self, track_set):
        log_age = 9.0
        with pytest.warns(SynthesizedProductWarning):
            iso = synthesize_isochrone(track_set, log_age)
        masses = iso.unified["initial_mass"]
        np.testing.assert_allclose(masses, [0.6, 0.8, 1.0])
        assert iso.identity.product == "synthesized_isochrones"
        assert iso.selection["log_age"] == log_age
        # all three tracks cover 1 Gyr: nothing omitted
        assert iso.native.metadata["n_tracks_used"] == 3
        omitted = iso.native.metadata["omitted"]
        assert len(omitted) == 1  # the HB track, excluded by policy
        assert omitted[0][1] == "hb track excluded from synthesis"

    def test_interpolation_hits_the_golden_node(self, track_set):
        # at exactly the 0.8 track's model age, the synthesized row is
        # that model (linear interpolation on a node is the node)
        log_age = math.log10(GOLDEN_AGE_YR)
        with pytest.warns(SynthesizedProductWarning):
            iso = synthesize_isochrone(track_set, log_age)
        masses = np.asarray(iso.unified["initial_mass"], dtype=float)
        i = int(np.argmin(np.abs(masses - 0.8)))
        assert iso.unified["log_luminosity"][i] == pytest.approx(
            GOLDEN["log_luminosity"], abs=5e-4
        )
        assert iso.unified["log_effective_temperature"][i] == pytest.approx(
            GOLDEN["log_effective_temperature"], abs=5e-4
        )
        assert iso.unified["log_radius"][i] == pytest.approx(
            GOLDEN["log_radius_cm"] - math.log10(6.957e10), abs=5e-4
        )
        assert iso.unified["phase"][i] == "main_sequence"

    def test_radiative_closure_of_synthesized_rows(self, track_set):
        # L = 4 pi R^2 sigma T^4 against the synthesized columns
        with pytest.warns(SynthesizedProductWarning):
            iso = synthesize_isochrone(track_set, 9.0)
        r_rsun = 10.0 ** np.asarray(iso.unified["log_radius"], dtype=float)
        teff = 10.0 ** np.asarray(
            iso.unified["log_effective_temperature"], dtype=float
        )
        log_l_closed = 2 * np.log10(r_rsun) + 4 * np.log10(teff / 5772.0)
        np.testing.assert_allclose(
            iso.unified["log_luminosity"], log_l_closed, atol=0.02
        )

    def test_gravity_closure_of_synthesized_rows(self, track_set):
        with pytest.warns(SynthesizedProductWarning):
            iso = synthesize_isochrone(track_set, 9.0)
        mass = np.asarray(iso.unified["current_mass"], dtype=float)
        r_rsun = 10.0 ** np.asarray(iso.unified["log_radius"], dtype=float)
        expected = np.log10(
            6.67430e-8 * mass * 1.98847e33 / (r_rsun * 6.957e10) ** 2
        )
        np.testing.assert_allclose(
            iso.unified["log_surface_gravity"], expected, atol=1e-9
        )

    def test_track_beyond_end_is_omitted_with_reason(self, track_set):
        # the 1.0 Msun fixture track ends at log_age ~9.75
        with pytest.warns(SynthesizedProductWarning):
            iso = synthesize_isochrone(track_set, 10.0)
        masses = list(np.asarray(iso.unified["initial_mass"]))
        assert masses == [0.6, 0.8]
        omitted = dict(
            (m, r) for m, r in iso.native.metadata["omitted"]
        )
        assert 1.0 in omitted
        assert "beyond track end" in omitted[1.0]

    def test_age_no_track_covers_fails_loudly(self, track_set):
        # no warning fires on this path: nothing was synthesized
        with pytest.raises(DataIntegrityError, match="no track covers"):
            synthesize_isochrone(track_set, 11.0)

    def test_provenance_records_the_transformation(self, track_set):
        with pytest.warns(SynthesizedProductWarning):
            iso = synthesize_isochrone(track_set, 9.0)
        assert any(
            "linear interpolation in age" in t for t in iso.provenance.transformations
        )
        assert iso.provenance.scientific_references  # PARSEC citations carry over
        assert any(
            "stellariso.synthesis" in r.citation
            for r in iso.provenance.software_references
        )

    def test_set_and_facade_roundtrip(self, track_set):
        with pytest.warns(SynthesizedProductWarning):
            isochrones = synthesize_isochrones(track_set, [9.0, 9.5])
        assert len(isochrones) == 2
        facade = ParsecIso([isochrones])
        value = facade.get_logg(mass=0.8, log_age=9.0, selection="exact")
        assert 3.0 < value < 5.0
        record = facade.last_record
        assert record.coordinate == "initial_mass"

    def test_method_guard(self, track_set):
        with pytest.raises(ValueError, match="linear"):
            synthesize_isochrone(track_set, 9.0, method="pchip")


class TestPhaseBoundaryBehavior:
    def test_boundary_straddle_reports_unknown(self, track_set):
        # find an age where the 0.8 track sits between integer phase codes
        track = track_set.tracks[1]
        phases = np.asarray(track.native["PHASE"], dtype=float)
        ages = np.asarray(track.native["AGE"], dtype=float)
        target = None
        for i in range(len(ages) - 1):
            if math.floor(phases[i] + 1e-9) != math.floor(phases[i + 1] + 1e-9):
                # an interior interpolation between the two models
                target = math.log10(math.sqrt(ages[i] * ages[i + 1]))
                if phases[i + 1] - phases[i] > 0.5:
                    break
        if target is None:
            pytest.skip("fixture has no fractional phase boundary")
        with pytest.warns(SynthesizedProductWarning):
            iso = synthesize_isochrone(track_set, target)
        masses = np.asarray(iso.unified["initial_mass"], dtype=float)
        i = int(np.argmin(np.abs(masses - 0.8)))
        # the straddled row is reported unknown (with a warning), never a guess
        assert iso.unified["phase"][i] == "unknown"
