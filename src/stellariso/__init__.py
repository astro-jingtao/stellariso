"""stellariso: faithful and unified access to single-star theoretical isochrones.

stellariso is a provenance-first, model-agnostic Python interface for reading,
preserving, standardizing, and querying tabulated theoretical isochrones from
single-star evolution models.
"""

__version__ = "0.1.0"

from .core import FieldSpec, ModelIdentity, ParameterRole, ParameterSpec
from .exceptions import StellarIsoError
from .facade import MistIso, UnifiedIso, construct
from .grid import IsochroneGrid, open_grid
from .interp import InterpolationRecord, interpolate_along
from .isochrone import Isochrone, IsochroneSet
from .native import NativeTable
from .provenance import (
    DataAsset,
    Provenance,
    Reference,
    SourceChain,
    SourceClass,
    SourceRecord,
)
from .retrieval import fetch
from .unified import PhaseMapping, UnifiedView

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
    # interpolation
    "InterpolationRecord",
    "interpolate_along",
    # errors
    "StellarIsoError",
]

