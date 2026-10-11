"""Tests for the core schema objects."""

from __future__ import annotations

import dataclasses

import pytest

from stellariso.core import (
    FieldOrigin,
    FieldSpec,
    ModelIdentity,
    ParameterRole,
    ParameterSource,
    ParameterSpec,
)


class TestParameterSpec:
    def test_axis_requires_values(self):
        with pytest.raises(ValueError, match="requires 'values'"):
            ParameterSpec(name="initial_feh", role=ParameterRole.AXIS)

    def test_fixed_requires_value(self):
        with pytest.raises(ValueError, match="requires 'value'"):
            ParameterSpec(name="alpha_fe", role=ParameterRole.FIXED)

    def test_derived_requires_relation(self):
        with pytest.raises(ValueError, match="requires"):
            ParameterSpec(name="initial_helium", role=ParameterRole.DERIVED)

    def test_value_and_values_are_exclusive(self):
        with pytest.raises(ValueError, match="both"):
            ParameterSpec(
                name="x",
                role=ParameterRole.FIXED,
                value=0.4,
                values=(0.0, 0.4),
            )

    def test_axis_spec_roundtrip(self):
        spec = ParameterSpec(
            name="initial_feh",
            role=ParameterRole.AXIS,
            values=(-1.0, -0.5, 0.0, 0.25),
            unit="dex",
            convention="log10(Z/Zsun) scaled-solar from form field",
            source=ParameterSource.OFFICIAL_DOCUMENTATION,
        )
        d = spec.to_dict()
        assert d["role"] == "axis"
        again = ParameterSpec.from_dict(d)
        assert again == spec

    def test_derived_helium_example(self):
        spec = ParameterSpec(
            name="initial_helium",
            role=ParameterRole.DERIVED,
            depends_on=("initial_z",),
            relation="Y_p + dYdZ * initial_z",
            relation_parameters={"Y_p": 0.2485, "dYdZ": 1.78},
            source=ParameterSource.DERIVED_FROM_OFFICIAL_RELATION,
        )
        assert spec.relation_parameters["dYdZ"] == 1.78

    def test_implicit_not_reported(self):
        spec = ParameterSpec(
            name="mixing_length",
            role=ParameterRole.IMPLICIT,
            status="not_reported",
        )
        assert spec.value is None

    def test_values_list_coerced_to_tuple(self):
        spec = ParameterSpec(
            name="initial_rotation", role=ParameterRole.AXIS, values=[0.0, 0.4]
        )
        assert spec.values == (0.0, 0.4)


class TestFieldSpec:
    def test_native_requires_native_name(self):
        with pytest.raises(ValueError, match="native_name"):
            FieldSpec(name="current_mass")

    def test_transformed_requires_transformation(self):
        with pytest.raises(ValueError, match="transformation"):
            FieldSpec(
                name="radius",
                native_name="log_R",
                origin=FieldOrigin.TRANSFORMED_NATIVE,
            )

    def test_native_field(self):
        spec = FieldSpec(
            name="current_mass",
            native_name="star_mass",
            unit="Msun",
            native_unit="Msun",
            backend="mist",
            mapping_version="1",
        )
        assert spec.origin is FieldOrigin.NATIVE
        assert spec.to_dict()["origin"] == "native"
        assert FieldSpec.from_dict(spec.to_dict()) == spec

    def test_transformed_field(self):
        spec = FieldSpec(
            name="effective_temperature",
            native_name="log_Teff",
            unit="K",
            native_unit="dex(K)",
            representation="linear",
            origin=FieldOrigin.TRANSFORMED_NATIVE,
            transformation="10 ** log_Teff",
        )
        d = spec.to_dict()
        again = FieldSpec.from_dict(d)
        assert again == spec
        assert again.transformation == "10 ** log_Teff"


class TestModelIdentity:
    def test_label(self):
        ident = ModelIdentity(
            family="mist",
            release="1.2",
            product="theoretical_isochrones",
            physics_configuration="vvcrit0.4",
        )
        assert ident.label == "mist/1.2/vvcrit0.4"

    def test_roundtrip(self):
        ident = ModelIdentity(
            family="parsec",
            release="v1.2S+COLIBRI PR16",
            product="theoretical_isochrones",
        )
        assert ModelIdentity.from_dict(ident.to_dict()) == ident


class TestFrozensess:
    def test_specs_are_frozen(self):
        spec = ParameterSpec(name="alpha_fe", role=ParameterRole.FIXED, value=0.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.value = 0.2
