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
