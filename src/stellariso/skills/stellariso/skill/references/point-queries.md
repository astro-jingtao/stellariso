# Point queries through the facade

The facade (`MistIso` / `ParsecIso`, both `UnifiedIso`) wraps one whole
model product and answers single-star queries directly. Read this file
when writing more than a one-line query, or when a query fails.

## Building the facade

```python
import stellariso

mist = stellariso.construct("mist/1.2", paths=["...iso"])
mist = stellariso.construct("mist/1.2", database=db, label="vvcrit0.4_full_isos")
```

- `model` is version-qualified (`"mist/1.2"`); a bare family is
  rejected. The release is validated against what the files state — a
  mismatch raises and names the release the files actually carry.
- Exactly one of `paths=` or `database=`; passing both raises.
- `paths` accepts one path or an iterable of files and directories.
- `database` accepts a path or an open `Database`; when a release
  publishes several products (MIST rotation or column variants),
  `label=` picks one — leaving it off with several candidates raises
  and lists the available labels.
- Discover a PARSEC release string by opening a table you hold:
  `stellariso.open_grid(path).identity.release`, then construct with
  `"parsec/" + that release`.
- `construct("mist")` without data raises by design (Hard Rule R4):
  MIST data is never fetched on demand.

## The query methods

```python
value = mist.get("log_surface_gravity", mass=1.0, log_age=9.5, initial_feh=0.0)
value, record = mist.get_detailed("log_surface_gravity", mass=1.0, log_age=9.5,
                                  initial_feh=0.0, interp="pchip")
```

- `field` — a unified field name (preferred; `sorted(iso.field_specs)`
  lists them) or a native column name of the file.
- `mass` — initial mass, in solar masses; the within-isochrone
  coordinate of every query.
- `log_age` and the remaining keywords are the grid coordinates: MIST
  takes `initial_feh`, `alpha_fe`, `initial_rotation`; PARSEC takes
  `initial_z`. Axes with several values in the loaded product must be
  pinned; the error message lists the available axes and values.
- `selection="nearest"` (the facade default) snaps each requested
  coordinate to the nearest available value; any snapping emits
  `NearestGridPointWarning` carrying the distances. `selection="exact"`
  raises `GridPointNotFoundError` on a miss. Unique-valued axes are
  filled automatically in both modes.
- `interp="linear"` or `"pchip"` — the within-isochrone method along
  `initial_mass`. A mass outside the tabulated range raises
  `UnsafeInterpolationError` (no extrapolation, Hard Rule R2).
- `mist.last_record` — the `InterpolationRecord` of the most recent
  `get`/`get_detailed` call: coordinate, method, requested values,
  bracketing node indices, node values, and the nodes' evolutionary
  phases. Use it whenever the number's provenance must be reported.

Convenience wrappers with the same signature:
`get_logg`, `get_log_teff`, `get_log_luminosity`, `get_log_radius`,
`get_current_mass`, and `get_phase` (below).

## Phase queries

`get_phase(mass, log_age=None, **kw)` returns the unified evolutionary
stage (for example `"main_sequence"`). Phases are discrete — nothing is
interpolated: the value is read from the bracketing mass nodes; when
they disagree the answer is `"unknown"` with a `PhaseMappingWarning`.
`selection=` may be passed through `kw`.

## Frequently used unified fields

`initial_mass`, `current_mass`, `log_effective_temperature`,
`log_surface_gravity`, `log_luminosity`, `log_radius`, `phase`. The
full vocabulary is registry-driven and product-dependent — always
introspect (`sorted(iso.field_specs)`) rather than assuming a name.

## Errors and what they mean

| Signal | Meaning | Response |
| ------ | ------- | -------- |
| `ValueError: model must be version-qualified` | bare family name passed | pass `"family/release"` |
| `ValueError: ... does not match the data` | the files state a different release than `model=` | fix the model string or the files |
| `GridPointNotFoundError` | exact miss, unpinned multi-valued axis, or no candidate after snapping | pin the listed axes; use `selection="nearest"` knowingly |
| `UnsafeInterpolationError` | queried mass outside the tabulated range | move the query inside the range; never extrapolate |
| `ValueError` from `construct('mist')` without data | no `paths=`/`database=` | build a database first (R4) |
| `NearestGridPointWarning` | the answer comes from a snapped grid point | report the substitution; do not silence |
