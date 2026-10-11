"""Tests for the native table and the isochrone/isochrone-set objects."""

from __future__ import annotations

import numpy as np
import pytest
from astropy.table import Table

from stellariso.core import ModelIdentity, ParameterRole, ParameterSpec
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.native import NativeTable


def make_native(rows=None, cols=("EEP", "initial_mass", "log_g")):
    rows = rows or [(1, 1.0, 4.0), (2, 1.2, 3.9), (3, 1.4, 3.5)]
    t = Table(rows=rows, names=cols)
    return NativeTable(
        table=t,
        header=("# MIST version number  = 1.2", "# EEP initial_mass log_g"),
        metadata={"version": "1.2"},
    )


class TestNativeTable:
    def test_preserves_columns_and_order(self):
        nat = make_native()
        assert nat.columns == ["EEP", "initial_mass", "log_g"]

    def test_column_access(self):
        nat = make_native()
        assert np.allclose(nat["initial_mass"], [1.0, 1.2, 1.4])
        assert "log_g" in nat
        assert "missing" not in nat

    def test_header_and_metadata_kept(self):
        nat = make_native()
        assert nat.header[0].startswith("# MIST")
        assert nat.metadata == {"version": "1.2"}

    def test_requires_astropy_table(self):
        with pytest.raises(TypeError):
            NativeTable(table=[[1, 2], [3, 4]])

    def test_equality(self):
        a, b = make_native(), make_native()
        assert a == b
        c = make_native(rows=[(1, 1.0, 4.0)])
        assert a != c

    def test_numeric_fidelity(self):
        # values pass through unchanged, no re-typing beyond float parsing
        vals = [(202, 0.9999999, 4.4381234)]
        nat = make_native(rows=vals)
        assert nat["EEP"][0] == 202
        assert nat["log_g"][0] == 4.4381234


class TestIsochrone:
    def test_holds_layers(self):
        nat = make_native()
        iso = Isochrone(
            native=nat,
            identity=ModelIdentity(
                family="mist", release="1.2", product="theoretical_isochrones"
            ),
            selection={"log_age": 9.0},
        )
        assert iso.native is nat
        assert len(iso) == 3
        assert iso.identity.family == "mist"

    def test_unified_view_absent_raises(self):
        iso = Isochrone(
            native=make_native(),
            identity=ModelIdentity(
                family="mist", release="1.2", product="theoretical_isochrones"
            ),
        )
        with pytest.raises(AttributeError, match="unified"):
            iso.unified

    def test_parameter_lookup(self):
        spec = ParameterSpec(name="alpha_fe", role=ParameterRole.FIXED, value=0.0)
        iso = Isochrone(
            native=make_native(),
            identity=ModelIdentity(
                family="mist", release="1.2", product="theoretical_isochrones"
            ),
            parameters=(spec,),
        )
        assert iso.parameter("alpha_fe").value == 0.0
        assert iso.parameter_value("alpha_fe") == 0.0
        with pytest.raises(KeyError):
            iso.parameter("nonexistent")

    def test_axis_parameter_requires_selection_pin(self):
        spec = ParameterSpec(name="log_age", role=ParameterRole.AXIS, values=(9.0, 9.5))
        iso = Isochrone(
            native=make_native(),
            identity=ModelIdentity(
                family="mist", release="1.2", product="theoretical_isochrones"
            ),
            parameters=(spec,),
            selection={"log_age": 9.5},
        )
        assert iso.parameter_value("log_age") == 9.5
        iso2 = Isochrone(
            native=make_native(),
            identity=iso.identity,
            parameters=(spec,),
        )
        with pytest.raises(KeyError, match="axis"):
            iso2.parameter_value("log_age")


class TestIsochroneSet:
    def test_set_of_isochrones(self):
        ident = ModelIdentity(
            family="mist", release="1.2", product="theoretical_isochrones"
        )
        nat = make_native()
        isos = tuple(
            Isochrone(native=nat, identity=ident, selection={"log_age": la})
            for la in (9.0, 9.5, 10.0)
        )
        s = IsochroneSet(isochrones=isos, native=nat, identity=ident, indexer="log_age")
        assert len(s) == 3
        assert s.keys() == [9.0, 9.5, 10.0]
        assert s[0] is isos[0]
        assert list(iter(s)) == list(isos)
