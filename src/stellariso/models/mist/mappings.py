"""MIST unified field mapping and phase mapping.

Column meanings follow the official MIST table README ("List of Header
Columns"; README_tables.pdf): the ``phase`` column is the FSPS phase type
(-1=PMS, 0=MS, 2=RGB, 3=CHeB, 4=EAGB, 5=TPAGB, 6=postAGB, 9=WR, with a
documented MS/WR overlap caution for very massive stars). The same document
defines the primary EEPs (1=PMS, 202=ZAMS, 353=IAMS, 454=TAMS, 605=RGB Tip,
631=ZACHeB, 707=TACHeB, 808=TPAGB or C-burn, 1409=post-AGB, 1710=WDCS).

Note on stage granularity: MIST's RGB code (2) covers the subgiant branch
and the RGB together; stellariso maps it to ``red_giant_branch`` rather than
splitting it. Phase 6 (postAGB) spans post-AGB through the white-dwarf
cooling sequence; it maps to ``post_agb`` and must not be read as an
enumerated WD population.
"""

from __future__ import annotations

from ...core import FieldOrigin, FieldSpec
from ...unified import PhaseMapping

__all__ = ["MIST_FIELD_SPECS", "MIST_PHASE_MAPPING", "MIST_EEP_ANCHORS"]

MAPPING_VERSION = "1"

_B = "mist"
_V = MAPPING_VERSION


def _native(name: str, unit: str | None = None, representation: str = "linear",
            native_name: str | None = None,
            description: str | None = None) -> FieldSpec:
    return FieldSpec(
        name=name,
        native_name=native_name if native_name is not None else name,
        unit=unit,
        native_unit=unit,
        representation=representation,
        origin=FieldOrigin.NATIVE,
        backend=_B,
        mapping_version=_V,
        description=description,
    )


def _transformed(name: str, native_name: str, unit: str | None,
                 native_unit: str | None, transformation: str = "10 ** x",
                 description: str | None = None) -> FieldSpec:
    return FieldSpec(
        name=name,
        native_name=native_name,
        unit=unit,
        native_unit=native_unit,
        representation="linear",
        origin=FieldOrigin.TRANSFORMED_NATIVE,
        transformation=transformation,
        backend=_B,
        mapping_version=_V,
        description=description,
    )


MIST_FIELD_SPECS = (
    _native("eep", native_name="EEP",
            description="equivalent evolutionary phase number"),
    _native("initial_mass", "solMass",
            description="mass at age zero of the model "
            "whose isochrone point this row interpolates"),
    _native("current_mass", "solMass", native_name="star_mass",
            description="actual (wind-reduced) mass at this point; MIST v1.2 "
            "uses Reimers-type RGB winds with efficiency anchored near "
            "eta ~ 0.1 and Blöcker-type AGB winds"),
    _native("log_effective_temperature", "dex(K)", "log",
            native_name="log_Teff"),
    _transformed("effective_temperature", "log_Teff", "K", "dex(K)"),
    _native("log_luminosity", "dex(solLum)", "log", native_name="log_L"),
    _native("log_surface_gravity", "dex(cm / s2)", "log", native_name="log_g"),
    _native("log_radius", "dex(solRad)", "log", native_name="log_R"),
    _transformed("radius", "log_R", "solRad", "dex(solRad)"),
    _native("native_phase", native_name="phase",
            description="FSPS phase code as printed by MIST"),
    FieldSpec(
        name="phase",
        native_name="phase",
        unit=None,
        native_unit=None,
        representation="linear",
        origin=FieldOrigin.DERIVED,
        transformation=(
            "MIST FSPS phase code mapped to unified coarse stages "
            f"(mapping version {_V}); codes 1, 7, 8 are not used by MIST"
        ),
        backend=_B,
        mapping_version=_V,
        description="unified coarse evolutionary stage",
    ),
    _native("mass_loss_rate", "Msun/yr", native_name="star_mdot",
            description="stellar mass-loss rate; negative means the star is "
            "losing mass (MIST sign convention)"),
    _native("he_core_mass", "solMass"),
)

MIST_PHASE_MAPPING = PhaseMapping(
    backend=_B,
    version=_V,
    table={
        -1: "pre_main_sequence",
        0: "main_sequence",
        2: "red_giant_branch",
        3: "core_helium_burning",
        4: "early_asymptotic_giant_branch",
        5: "thermally_pulsing_asymptotic_giant_branch",
        6: "post_agb",
        9: "wolf_rayet",
    },
)

# Primary EEPs as defined by the official MIST tables README.
MIST_EEP_ANCHORS = {
    "PMS": 1,
    "ZAMS": 202,
    "IAMS": 353,
    "TAMS": 454,
    "RGB_TIP": 605,
    "ZACHeB": 631,
    "TACHeB": 707,
    "TPAGB_START": 808,
    "POST_AGB": 1409,
    "WDCS": 1710,
}
