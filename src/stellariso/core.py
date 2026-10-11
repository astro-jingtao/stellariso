"""Core schema objects: model identity, parameter specs, field specs.

These frozen dataclasses are the vocabulary every backend speaks. They carry
no model-specific logic; backends construct them from native data and
official documentation. See ``docs/data-sources.md`` for the upstream sources
themselves.
"""

from __future__ import annotations

import dataclasses
from enum import Enum

__all__ = [
    "ParameterRole",
    "ParameterSource",
    "ParameterSpec",
    "FieldSpec",
    "FieldOrigin",
    "ModelIdentity",
]


class ParameterRole(Enum):
    """The role a physical parameter plays in a given model product.

    ``axis``
        The parameter varies across the published grid.
    ``fixed``
        The parameter is held at a known value for the whole product.
    ``derived``
        The parameter is determined by other parameters through a stated
        relation (for example ``Y = Y_p + dY/dZ * Z``).
    ``implicit``
        The model computation necessarily used the parameter, but its value
        cannot be recovered from the published data.
    ``unknown``
        stellariso has not verified the parameter for this product.
    ``not_applicable``
        The parameter does not exist under this product's physics.
    """

    AXIS = "axis"
    FIXED = "fixed"
    DERIVED = "derived"
    IMPLICIT = "implicit"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ParameterSource(Enum):
    """Where a parameter's value comes from."""

    NATIVE = "native"  # printed in the data product itself
    OFFICIAL_DOCUMENTATION = "official_documentation"
    SCIENTIFIC_PUBLICATION = "scientific_publication"
    DERIVED_FROM_OFFICIAL_RELATION = "derived_from_official_relation"
    DERIVED_BY_STELLARISO = "derived_by_stellariso"
    USER_PROVIDED = "user_provided"
    NOT_REPORTED = "not_reported"


_ROLE_REQUIRES = {
    ParameterRole.AXIS: ("values",),
    ParameterRole.FIXED: ("value",),
    ParameterRole.DERIVED: ("depends_on", "relation"),
}


@dataclasses.dataclass(frozen=True)
class ParameterSpec:
    """Description of one physical parameter of a model product.

    The five value notions are kept distinct: ``values`` (available grid
    values), ``value`` (the fixed value), ``reference_value`` /
    ``default_selection`` are recorded by the grid API on top of specs, and
    user overrides are user input — none of them collapse into each other.
    """

    name: str
    role: ParameterRole
    value: float | int | str | None = None
    values: tuple | None = None
    unit: str | None = None
    convention: str | None = None
    description: str | None = None
    depends_on: tuple[str, ...] = ()
    relation: str | None = None
    relation_parameters: dict | None = None
    source: ParameterSource | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, ParameterRole):
            raise TypeError(f"role must be a ParameterRole, got {self.role!r}")
        if self.value is not None and self.values is not None:
            raise ValueError("ParameterSpec cannot carry both value and values")
        required = _ROLE_REQUIRES.get(self.role, ())
        for attr in required:
            present = getattr(self, attr)
            if present is None or present == () or present == "":
                raise ValueError(
                    f"role={self.role.value} requires {attr!r} on parameter "
                    f"{self.name!r}"
                )
        if self.values is not None and not isinstance(self.values, tuple):
            object.__setattr__(self, "values", tuple(self.values))

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["role"] = self.role.value
        if self.source is not None:
            d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ParameterSpec":
        d = dict(d)
        d["role"] = ParameterRole(d["role"])
        if d.get("source") is not None:
            d["source"] = ParameterSource(d["source"])
        return cls(**d)


class FieldOrigin(Enum):
    """Where a unified field's values come from."""

    NATIVE = "native"  # same numbers, possibly renamed
    TRANSFORMED_NATIVE = "transformed_native"  # unit or representation change
    DERIVED = "derived"  # computed from several native fields
    MISSING = "missing"  # no source in this product


@dataclasses.dataclass(frozen=True)
class FieldSpec:
    """Description of one unified-layer field and how it maps to native data.

    A unified field must always be traceable back to native columns; this
    spec is that trace. ``transformation`` is a human-readable statement of
    any conversion applied (it documents, it does not execute).
    """

    name: str
    native_name: str | None = None
    unit: str | None = None
    native_unit: str | None = None
    representation: str = "linear"  # "linear" | "log"
    origin: FieldOrigin = FieldOrigin.NATIVE
    transformation: str | None = None
    description: str | None = None
    backend: str | None = None
    mapping_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.origin, FieldOrigin):
            raise TypeError(f"origin must be a FieldOrigin, got {self.origin!r}")
        if self.origin is FieldOrigin.NATIVE and self.native_name is None:
            raise ValueError(
                f"field {self.name!r} with origin=native must declare native_name"
            )
        if self.origin in (FieldOrigin.TRANSFORMED_NATIVE,) and (
            self.native_name is None or self.transformation is None
        ):
            raise ValueError(
                f"field {self.name!r} with origin=transformed_native must "
                "declare native_name and transformation"
            )
        if self.origin is FieldOrigin.DERIVED and self.transformation is None:
            raise ValueError(
                f"field {self.name!r} with origin=derived must declare transformation"
            )

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["origin"] = self.origin.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FieldSpec":
        d = dict(d)
        d["origin"] = FieldOrigin(d["origin"])
        return cls(**d)


@dataclasses.dataclass(frozen=True)
class ModelIdentity:
    """Identity of the model product an object was built from.

    ``family``/``release``/``product`` must be enough to distinguish e.g.
    Padova vs PARSEC vs PARSEC+COLIBRI, or MIST v1.2 vs v2.x;
    ``physics_configuration`` disambiguates rotation, [alpha/Fe], and similar
    axes within one release.
    """

    family: str  # "mist", "parsec", ...
    release: str  # "1.2", "2.0", "v1.2S+COLIBRI PR16", ...
    product: str  # "theoretical_isochrones", ...
    version: str | None = None  # finer upstream version if distinct from release
    physics_configuration: str | None = None
    description: str | None = None

    @property
    def label(self) -> str:
        parts = [self.family, self.release]
        if self.physics_configuration:
            parts.append(self.physics_configuration)
        return "/".join(parts)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelIdentity":
        return cls(**d)
