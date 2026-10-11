"""PARSEC unified field mapping and phase mapping.

Column names follow the CMD isochrone-table format (see the reader module).
Stage labels follow the official CMD FAQ: 0=PMS, 1=MS, 2=SGB, 3=RGB,
(4,5,6)=different stages of CHEB, 7=EAGB, 8=TP-AGB, 9=post-AGB — with the
FAQ's own caution that labels are approximate and not carefully checked for
all masses and metallicities.

Mass-loss sign convention difference: MIST's ``star_mdot`` is negative while
the star loses mass; CMD's ``logMdot`` is log10 of the (positive) mass-loss
rate in Msun/yr. Both are preserved natively; the unified
``mass_loss_rate`` is only mapped for MIST, and PARSEC keeps ``logMdot``
under its native name to avoid a silent sign/representation change.
"""

from __future__ import annotations

from stellariso.core import FieldOrigin, FieldSpec
from stellariso.unified import PhaseMapping

__all__ = ["PARSEC_FIELD_SPECS", "PARSEC_PHASE_MAPPING", "PARSEC_REFERENCES"]

MAPPING_VERSION = "1"

_B = "parsec"
_V = MAPPING_VERSION


def _native(name, native_name, unit=None, representation="linear", description=None):
    return FieldSpec(
        name=name,
        native_name=native_name,
        unit=unit,
        native_unit=unit,
        representation=representation,
        origin=FieldOrigin.NATIVE,
        backend=_B,
        mapping_version=_V,
        description=description,
    )


PARSEC_FIELD_SPECS = (
    _native("initial_mass", "M_ini", "solMass",
            description="initial (age-zero) mass of the isochrone point"),
    _native("current_mass", "M_act", "solMass",
            description="actual mass including the mass-loss history "
            "(Reimers RGB winds with the eta stated in the file header)"),
    _native("log_luminosity", "logL/Lo", "dex(solLum)", "log"),
    _native("log_effective_temperature", "logTe", "dex(K)", "log"),
    _native("log_surface_gravity", "logG", "dex(cm / s2)", "log"),
    _native("native_phase", "label",
            description="CMD evolutionary stage label (approximate per the "
            "official FAQ)"),
    FieldSpec(
        name="phase",
        native_name="label",
        origin=FieldOrigin.DERIVED,
        transformation=(
            "CMD stage label mapped to unified coarse stages "
            f"(mapping version {_V})"
        ),
        backend=_B,
        mapping_version=_V,
        description="unified coarse evolutionary stage",
    ),
    _native("imf_integral", "int_IMF",
            description="integral of the selected IMF (in number of stars, "
            "normalised to 1 Msun of initially formed stars) from 0 up to "
            "the current M_ini"),
    _native("c_over_o", "C/O",
            description="photospheric C/O ratio (ZAMS value printed before "
            "the TP-AGB)"),
    _native("he_core_mass_tp", "M_hec", "solMass",
            description="H-exhausted core mass on the TP-AGB (0 before it)"),
    _native("log_mass_loss_rate", "logMdot", None, "log",
            description="log10 of the mass-loss rate in Msun/yr (positive "
            "quantity; meaningful mainly on the TP-AGB)"),
)

PARSEC_PHASE_MAPPING = PhaseMapping(
    backend=_B,
    version=_V,
    table={
        0: "pre_main_sequence",
        1: "main_sequence",
        2: "subgiant",
        3: "red_giant_branch",
        4: "core_helium_burning",
        5: "core_helium_burning",
        6: "core_helium_burning",
        7: "early_asymptotic_giant_branch",
        8: "thermally_pulsing_asymptotic_giant_branch",
        9: "post_agb",
    },
)
