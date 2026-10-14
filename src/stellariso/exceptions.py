"""Exception hierarchy for stellariso.

All errors raised by stellariso derive from :class:`StellarIsoError`, so
callers can catch the library's failures as a group. Errors are raised loudly
rather than silently worked around; fallbacks that do exist (for example,
nearest-grid-point selection) emit warnings and record provenance instead of
raising.
"""

__all__ = [
    "StellarIsoError",
    "UnsupportedModelError",
    "UnsupportedReleaseError",
    "UnrecognizedFormatError",
    "AmbiguousFormatError",
    "MissingParameterError",
    "ParameterNotReportedError",
    "GridPointNotFoundError",
    "GridBoundaryError",
    "UnsafeInterpolationError",
    "AmbiguousConventionError",
    "MetadataConflictError",
    "DataIntegrityError",
    "SourceUnavailableError",
    "LicenseUnavailableError",
    "CmdFormError",
]


class StellarIsoError(Exception):
    """Base class for all stellariso errors."""


class UnsupportedModelError(StellarIsoError):
    """The requested model family has no registered backend."""


class UnsupportedReleaseError(StellarIsoError):
    """The backend does not support the requested release of a model."""


class UnrecognizedFormatError(StellarIsoError):
    """No backend recognizes a data source as its native format."""


class AmbiguousFormatError(StellarIsoError):
    """More than one backend claims a data source; the caller must choose."""


class MissingParameterError(StellarIsoError):
    """A parameter required to identify or select an isochrone is absent."""


class ParameterNotReportedError(StellarIsoError):
    """A parameter value was requested that the upstream data does not report."""


class GridPointNotFoundError(StellarIsoError):
    """No isochrone exists at the requested grid coordinates (exact selection)."""


class GridBoundaryError(StellarIsoError):
    """The requested coordinates lie outside the grid's covered range."""


class UnsafeInterpolationError(StellarIsoError):
    """An interpolation was requested that stellariso refuses to perform
    silently (extrapolation, non-monotonic coordinate, phase crossing)."""


class AmbiguousConventionError(StellarIsoError):
    """A quantity or parameter is requested under a convention the data does
    not unambiguously support (for example a [Fe/H] from a Z-only product)."""


class MetadataConflictError(StellarIsoError):
    """Independent metadata sources disagree (file header vs filename vs
    user assertion)."""


class DataIntegrityError(StellarIsoError):
    """A downloaded or on-disk asset failed checksum or structural validation."""


class SourceUnavailableError(StellarIsoError):
    """All eligible sources for an asset failed; nothing was fetched."""


class LicenseUnavailableError(StellarIsoError):
    """The redistribution license of an asset could not be established."""


class CmdFormError(StellarIsoError):
    """The Padova CMD web form rejected, drifted from, or failed a
    submission (including the accepted-but-empty failure mode)."""
