"""stellariso: faithful and unified access to single-star theoretical isochrones.

stellariso is a provenance-first, model-agnostic Python interface for reading,
preserving, standardizing, and querying tabulated theoretical isochrones from
single-star evolution models.
"""

from stellariso._version import __version__
from stellariso.core import FieldSpec, ModelIdentity, ParameterRole, ParameterSpec
from stellariso.database.build import build_database
from stellariso.database.core import Database, open_database
from stellariso.database.inventory import refresh_database
from stellariso.database.transfer import merge_database
from stellariso.exceptions import StellarIsoError
from stellariso.facade import MistIso, PadovaIso, ParsecIso, UnifiedIso, construct
from stellariso.grid import IsochroneGrid, open_grid
from stellariso.interp import InterpolationRecord, interpolate_along
from stellariso.isochrone import Isochrone, IsochroneSet
from stellariso.native import NativeTable
from stellariso.provenance import (
    DataAsset,
    Provenance,
    Reference,
    SourceChain,
    SourceClass,
    SourceRecord,
)
from stellariso.skill import skill_directory
from stellariso.unified import PhaseMapping, UnifiedView

__all__ = [  # noqa: RUF022 — deliberately grouped by role, not sorted
    "__version__",
    # core schema
    "FieldSpec",
    "ModelIdentity",
    "ParameterRole",
    "ParameterSpec",
    # objects
    "Isochrone",
    "IsochroneSet",
    "IsochroneGrid",
    "NativeTable",
    "UnifiedView",
    "PhaseMapping",
    # provenance
    "Provenance",
    "SourceRecord",
    "SourceClass",
    "SourceChain",
    "DataAsset",
    "Reference",
    # entry points
    "open_grid",
    "construct",
    "build_database",
    "open_database",
    "Database",
    "merge_database",
    "refresh_database",
    "UnifiedIso",
    "MistIso",
    "PadovaIso",
    "ParsecIso",
    # interpolation
    "InterpolationRecord",
    "interpolate_along",
    # shipped skill
    "skill_directory",
    # errors
    "StellarIsoError",
]

