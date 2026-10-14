"""Warning categories for stellariso.

Warnings (unlike exceptions) cover situations where execution continues but
the result differs from what was literally asked for. Every warning category
here corresponds to a condition that is also recorded in provenance or in
selection metadata attached to the returned objects.
"""

__all__ = [
    "StellarIsoWarning",
    "NearestGridPointWarning",
    "DerivedQuantityWarning",
    "IncompleteMetadataWarning",
    "DeprecatedReleaseWarning",
    "PhaseMappingWarning",
    "ThirdPartySourceWarning",
    "ChecksumUnavailableWarning",
    "CatalogSizeMismatchWarning",
    "SynthesizedProductWarning",
    "CmdFormDriftWarning",
]


class StellarIsoWarning(UserWarning):
    """Base class for all stellariso warnings."""


class NearestGridPointWarning(StellarIsoWarning):
    """A nearest grid point was returned instead of the requested exact one."""


class DerivedQuantityWarning(StellarIsoWarning):
    """A quantity was derived from other quantities rather than read natively."""


class IncompleteMetadataWarning(StellarIsoWarning):
    """Metadata expected from the upstream product is missing or partial."""


class DeprecatedReleaseWarning(StellarIsoWarning):
    """The selected release is deprecated upstream."""


class PhaseMappingWarning(StellarIsoWarning):
    """A native phase code has no confident mapping to the coarse unified
    phase scheme, or a mapping crosses phase boundaries."""


class ThirdPartySourceWarning(StellarIsoWarning):
    """An asset was (or would be) obtained from a non-official source."""


class ChecksumUnavailableWarning(StellarIsoWarning):
    """No checksum is available to verify an asset's integrity."""


class CatalogSizeMismatchWarning(StellarIsoWarning):
    """A downloaded archive's size differs from the size recorded in the
    release catalog at verification time (the upstream file may have been
    replaced)."""


class SynthesizedProductWarning(StellarIsoWarning):
    """The product being read was synthesized locally from tracks (or
    otherwise derived) rather than published by the model team; its
    numbers follow stellariso's documented transformation, not the team's
    own isochrone pipeline."""


class CmdFormDriftWarning(StellarIsoWarning):
    """The live CMD web form declares fields the submitted payload does not
    send; if any of them is required upstream, the job will come back as a
    header-only table (which fetch_output refuses loudly)."""
