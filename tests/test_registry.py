"""Tests for the declarative unified-parameter registry."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from stellariso.core import FieldOrigin, ParameterRole, ParameterSource
from stellariso.provenance import Reference
from stellariso.registry import (
    REGISTRY_FILE,
    backend_names,
    backend_notes,
    eep_anchors,
    field_spec_dict,
    field_specs,
    load_registry,
    phase_code_meanings,
    phase_mapping,
    references,
    resolve_parameters,
    unified_field_names,
    unified_phases,
)

REPO_ROOT = Path(__file__).parent.parent


class TestRegistryData:
    def test_registry_file_ships_with_the_package(self):
        assert REGISTRY_FILE.exists()
        assert REGISTRY_FILE.suffix == ".json"

    def test_loads_and_lists_backends(self):
        reg = load_registry()
        assert set(backend_names()) == {"mist", "parsec"}
        assert reg["schema_version"] == 1

    def test_unified_vocabulary_present(self):
        names = unified_field_names()
        assert len(names) == len(set(names))
        for required in (
            "initial_mass",
            "log_surface_gravity",
            "phase",
            "effective_temperature",
        ):
            assert required in names
        assert "unknown" in unified_phases()


class TestFieldSpecs:
    def test_mist_specs_map_to_native_columns(self):
        specs = field_specs("mist")
        by_name = {s.name: s for s in specs}
        assert by_name["current_mass"].native_name == "star_mass"
        assert by_name["log_surface_gravity"].native_name == "log_g"
        assert by_name["eep"].native_name == "EEP"
        assert by_name["current_mass"].mapping_version == "1"

    def test_transformed_fields_declare_implemented_transformation(self):
        for backend in backend_names():
            for spec in field_specs(backend):
                if spec.origin is FieldOrigin.TRANSFORMED_NATIVE:
                    from stellariso.unified import TRANSFORMATIONS

                    assert spec.transformation in TRANSFORMATIONS
                    assert spec.native_unit is not None

    def test_parsec_specs(self):
        specs = field_spec_dict("parsec")
        assert specs["current_mass"].native_name == "M_act"
        assert specs["log_surface_gravity"].native_name == "logG"
        assert specs["log_mass_loss_rate"].native_name == "logMdot"


class TestPhaseMapping:
    def test_mist_phase_mapping_from_registry(self):
        mapping = phase_mapping("mist")
        out = mapping([0, 2, 9])
        assert list(out) == ["main_sequence", "red_giant_branch", "wolf_rayet"]

    def test_code_meanings_cover_the_table(self):
        for backend in backend_names():
            meanings = phase_code_meanings(backend)
            table = phase_mapping(backend).table
            assert set(meanings) == set(table)

    def test_eep_anchors_mist_only(self):
        assert eep_anchors("mist")["ZAMS"] == 202
        assert eep_anchors("parsec") is None


class TestResolveParametersMist:
    DYNAMIC = {
        "log_age": (9.0, 9.5),
        "initial_feh": (-1.0,),
        "alpha_fe": (0.0,),
        "initial_helium": 0.249,
        "initial_z": 0.00178,
    }

    def test_roles_and_values(self):
        specs = {p.name: p for p in resolve_parameters("mist", self.DYNAMIC)}
        assert specs["log_age"].role is ParameterRole.AXIS
        assert specs["log_age"].values == (9.0, 9.5)
        assert specs["log_age"].unit == "dex(log10(age/yr))"
        assert specs["initial_feh"].values == (-1.0,)
        assert specs["initial_helium"].role is ParameterRole.FIXED
        assert specs["initial_helium"].value == 0.249
        assert specs["initial_helium"].source is ParameterSource.NATIVE
        assert specs["initial_z"].value == 0.00178
        assert specs["initial_rotation"].values == (0.0, 0.4)
        assert specs["mixing_length"].role is ParameterRole.IMPLICIT
        assert specs["mixing_length"].status == "not_reported"

    def test_missing_required_dynamic_value_fails_loudly(self):
        dynamic = dict(self.DYNAMIC)
        del dynamic["initial_helium"]
        with pytest.raises(KeyError, match="initial_helium"):
            resolve_parameters("mist", dynamic)


class TestResolveParametersParsec:
    def test_with_z_and_eta(self):
        specs = {
            p.name: p
            for p in resolve_parameters(
                "parsec",
                {
                    "log_age": (9.0,),
                    "initial_z": (0.0152,),
                    "eta_reimers": 0.2,
                },
            )
        }
        assert specs["initial_z"].role is ParameterRole.AXIS
        assert specs["initial_z"].values == (0.0152,)
        assert specs["eta_reimers"].role is ParameterRole.FIXED
        assert specs["eta_reimers"].value == 0.2
        assert specs["initial_helium"].role is ParameterRole.DERIVED
        assert specs["initial_helium"].relation == "Y_p + dYdZ * initial_z"
        assert specs["initial_helium"].relation_parameters == {
            "Y_p": 0.2485,
            "dYdZ": 1.78,
        }
        assert specs["alpha_fe"].value == 0.0
        assert specs["initial_rotation"].role is ParameterRole.NOT_APPLICABLE

    def test_without_z_or_eta_selects_fallbacks(self):
        specs = {
            p.name: p
            for p in resolve_parameters("parsec", {"log_age": (9.0,)})
        }
        assert specs["initial_z"].role is ParameterRole.IMPLICIT
        assert specs["initial_z"].status == "not_in_file"
        assert "eta_reimers" not in specs


class TestReferencesAndNotes:
    def test_references_are_reference_objects(self):
        for backend in backend_names():
            refs = references(backend)
            assert refs and all(isinstance(r, Reference) for r in refs)
        assert references("mist")[0].bibcode == "2016ApJ...823..102C"

    def test_notes_exist(self):
        for backend in backend_names():
            assert backend_notes(backend)


class TestGeneratedDocument:
    def test_docs_unified_parameters_md_is_current(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "generate_parameter_docs.py"),
             "--check"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stdout + result.stderr
