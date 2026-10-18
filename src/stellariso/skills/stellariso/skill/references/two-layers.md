# The two-layer model: native and unified

Read this file when the data itself matters — whole tables, the file's
own columns, field mappings, physical parameters, or provenance — or
when interpolating along a coordinate other than initial mass.

## Opening a grid

```python
import stellariso

grid = stellariso.open_grid("path/to/file_or_directory")          # autodetect
grid = stellariso.open_grid("path", model="mist")                 # family given
grid = stellariso.open_grid("path", model="mist/1.2")             # release validated
```

Without `model=`, every registered backend sniffs the sources; exactly
one must claim them (`UnrecognizedFormatError` when none does,
`AmbiguousFormatError` when several do). A stated release is validated
against the files' own identity and a mismatch fails loudly.

## Selecting one isochrone

```python
iso = grid.get_isochrone(log_age=9.0, initial_feh=-1.0)           # method="exact" (default)
iso = grid.get_isochrone(log_age=9.2, method="nearest")           # snaps + warns
```

Selectable coordinates: MIST `log_age`, `initial_feh`, `alpha_fe`,
`initial_rotation`; PARSEC `log_age`, `initial_z`. Under `exact`,
axes the grid holds at a single value are filled automatically;
multi-valued axes left unpinned raise and list the available values.
Under `nearest`, each requested coordinate snaps independently and any
real snapping emits `NearestGridPointWarning` with the distances. The
returned `Isochrone` carries `iso.selection` (the values used) and
`iso.selection_info` (`method`, `requested`, `returned`, and under
`nearest` the per-axis `distances`).

## The two layers of one isochrone

```python
iso.native["log_g"]                    # the file's own column (NativeTable)
iso.native.columns                     # the file's own column names
iso.unified["log_surface_gravity"]     # the canonical name (UnifiedView)
iso.unified.field_names()
iso.field_info("log_surface_gravity")  # FieldSpec: unified -> native mapping
iso.to_table(layer="unified")          # astropy Table, either layer
```

Unified fields are also attributes: `iso.log_surface_gravity` works.
`field_info(name)` returns the `FieldSpec` tracing the unified field
back to native data (origin, transformation, units); `iso.has_field`
checks membership. The unified vocabulary is product-dependent —
introspect with `sorted(iso.field_specs)`.

## Physical parameters and identity

```python
iso.identity.label                     # e.g. 'mist/1.2/vvcrit0.4'
spec = iso.parameter("initial_rotation")   # ParameterSpec
spec.role                              # 'axis' | 'fixed' | 'derived' | 'implicit' | ...
iso.parameter_value("initial_rotation")   # constant or pinned-axis parameters only
```

Roles: `axis` (varies across the grid — readable only when the
selection pins it), `fixed` (held at a known value for the whole
product), `derived` (fixed by a stated relation, recorded with
`depends_on` and `relation`), `implicit` (the computation necessarily
used it but the published data cannot recover the value — asking for
the value raises and reports the status), plus `unknown` and
`not_applicable`. Never invent a value for an implicit parameter;
report it as not recoverable.

## Within-isochrone interpolation

```python
values = iso.at(1.0, fields=["log_surface_gravity", "log_luminosity"])
values, record = iso.at(1.0, fields="log_surface_gravity", method="pchip", record=True)
out, record = stellariso.interpolate_along(iso, "initial_mass", [0.8, 1.0, 1.2],
                                           ["log_surface_gravity"])
```

- `iso.at(mass, fields=None, coordinate="initial_mass", method="linear",
  record=False)` — `fields=None` means every interpolable unified field
  (discrete stage fields are excluded); a string field yields the single
  value, a list yields a dict.
- `interpolate_along` is the general form: any monotonic coordinate
  (unified field or native column), scalar or array queries, several
  fields at once. Fields resolve as unified names first, native columns
  second.
- Methods: `"linear"` and `"pchip"`. Queries outside the coordinate's
  tabulated range raise `UnsafeInterpolationError` — never extrapolate
  (Hard Rule R2).
- Both return an `InterpolationRecord` (with `record=True` for `at`):
  coordinate, method, requested values, bracketing node indices, node
  values, and the nodes' phases — the audit trail to persist with any
  derived number.

## Provenance

`iso.provenance` / `grid.provenance` — a `Provenance` aggregating the
source chain: `data_sources`, `assets`, `source_chains`,
`scientific_references`, `software_references`, `transformations`;
`to_dict()` is JSON-ready. When a result must be citable or auditable,
carry this object (or its dict) alongside the numbers.
