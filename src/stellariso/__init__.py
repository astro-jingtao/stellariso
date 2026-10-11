"""stellariso: faithful and unified access to single-star theoretical isochrones.

stellariso is a provenance-first, model-agnostic Python interface for reading,
preserving, standardizing, and querying tabulated theoretical isochrones from
single-star evolution models.
"""

__version__ = "0.1.0"

from stellariso.core import FieldSpec, ModelIdentity, ParameterRole, ParameterSpec
from stellariso.exceptions import StellarIsoError
from stellariso.facade import MistIso, ParsecIso, UnifiedIso, construct
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
from stellariso.retrieval import fetch
from stellariso.unified import PhaseMapping, UnifiedView

__all__ = [
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
    "fetch",
    "UnifiedIso",
    "MistIso",
    "ParsecIso",
    # interpolation
    "InterpolationRecord",
    "interpolate_along",
    # errors
    "StellarIsoError",
]

