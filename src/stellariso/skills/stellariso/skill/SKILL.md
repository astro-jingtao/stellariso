---
name: stellariso
description: Use the stellariso Python library to read, standardize, and query tabulated theoretical isochrones from the MIST and PARSEC single-star evolution models. Use when writing or running code that needs a stellar quantity at a given initial mass and age (log surface gravity, effective temperature, luminosity, radius, current mass, evolutionary phase), when selecting isochrones by age and composition, when opening MIST .iso files or PARSEC CMD web-form output tables, when building or querying the local isochrone database, or when fetching PARSEC isochrones through the official CMD web form programmatically. Also when stellariso raises GridPointNotFoundError or UnsafeInterpolationError, or warns about a nearest grid point, and the failure must be read correctly.
---

# stellariso usage

## Role

You write and run Python that uses stellariso — the provenance-first
reader and query interface for tabulated theoretical isochrones from
the MIST and PARSEC single-star evolution models. Your job is to pick
the right entry point, keep every query inside the library's
physics-safety contract, and read its errors and warnings as designed.

## The library in one screen

```text
files you hold ──open_grid──► IsochroneGrid
                                │   get_isochrone(log_age=…, initial_feh=…)
                                ▼
                             Isochrone          one age + composition slice
                                │   .native["log_g"]                  the file's own column
                                │   .unified["log_surface_gravity"]   the canonical name
                                │   .at(mass, fields=…)               within-slice interpolation

construct("mist/1.2", paths=… or database=…) ──► MistIso / ParsecIso   the point-query facade
                                │   .get("log_surface_gravity", mass, log_age, …)
                                │   .get_logg / get_log_teff / get_phase …
                                └   grid-point selection + within-slice interpolation,
                                    combined; the audit trail lands in .last_record
```

## Hard Rules

- **R1 — Never interpolate across isochrones.** Age and composition are
  selected, never blended: `selection="exact"` requires an available
  grid point, `selection="nearest"` snaps and warns
  (`NearestGridPointWarning`). Do not work around this by manually
  blending two isochrones — restate the query at an available grid
  point, or accept the nearest one knowingly.
- **R2 — Never extrapolate within an isochrone.** A queried mass
  outside the tabulated range raises `UnsafeInterpolationError`; widen
  or move the question instead of catching the error away.
- **R3 — Model strings are version-qualified.** `"mist/1.2"`, not
  `"mist"`: APIs that must know the release reject a bare family name.
  The stated release is validated against what the files say about
  themselves; the loud mismatch catches wrong files.
- **R4 — Data is never fetched on demand.** MIST: build a local
  database (`stellariso.build_database`) or pass `paths=` of files you
  hold. PARSEC publishes no isochrone packages at all: obtain tables
  through the official CMD web form (`CmdFormClient`, or the browser
  form) and pass the downloaded tables by path.
- **R5 — Read what the warnings say.** `NearestGridPointWarning` means
  the numbers come from a different grid point than the one requested;
  `PhaseMappingWarning` from `get_phase` means the mass straddles a
  phase boundary (the answer is `"unknown"`). Both are provenance, not
  noise; propagate them to the user, do not silence them.

## Decision table

| The task | Entry point | Depth |
| -------- | ----------- | ----- |
| One number (logg, Teff, …) at (mass, age, composition) | `construct(...)` then `get_logg(...)` / `get(...)` | references/point-queries.md |
| Whole tables, native columns, field mappings, parameters, provenance | `open_grid` → `get_isochrone` | references/two-layers.md |
| Many queries or interpolation along a custom coordinate | `iso.at(...)` / `interpolate_along(...)` | references/two-layers.md |
| Build, complete, or query the offline database | `build_database`, `open_database`, `construct(database=…)` | references/database.md |
| Obtain PARSEC isochrone tables | `CmdFormClient` + `CmdFieldSet` | references/parsec-cmd-form.md |

## Workflow — point query (the common case)

```python
import stellariso

mist = stellariso.construct("mist/1.2", paths=["MIST_v1.2_feh_p0.00_vvcrit0.4_full_isos.iso"])
mist.get_logg(mass=1.0, log_age=9.5, initial_feh=0.0)   # 4.460...
mist.get("log_effective_temperature", mass=1.0, log_age=9.5, initial_feh=0.0)
mist.get_phase(mass=1.0, log_age=9.5, initial_feh=0.0)  # 'main_sequence'
mist.last_record                                        # bracketing nodes and their phases
```

Data source is `paths=` (files or a directory you hold) or `database=`
(a built database; `label=` picks one product of a release) — never
both, never the network. Selection coordinates are keyword arguments:
`log_age` plus the family's composition axes (MIST: `initial_feh`,
`alpha_fe`, `initial_rotation`; PARSEC: `initial_z`); axes with several
values must be pinned. `selection=` (default `"nearest"`) and `interp=`
(`"linear"` or `"pchip"`) control the two halves of every query — full
semantics in references/point-queries.md.

## Workflow — two-layer access to the data

```python
grid = stellariso.open_grid("path/to/file_or_directory")   # autodetects the model
iso = grid.get_isochrone(log_age=9.5, initial_feh=0.0)     # exact by default
iso.native["log_g"]                     # the file's own column
iso.unified["log_surface_gravity"]      # the canonical name
iso.field_info("log_surface_gravity")   # how unified maps back to native
values = iso.at(1.0, fields=["log_surface_gravity"])       # within-isochrone interpolation
```

## Workflow — the local database

```python
stellariso.build_database("path/to/database", dry_run=True)   # the plan first
db = stellariso.build_database("path/to/database")            # completes what is missing
mist = stellariso.construct("mist/1.2", database=db, label="vvcrit0.4_full_isos")
```

There is no implicit cache location: `database=` is passed explicitly
everywhere, and after the build everything answers offline. Building,
moving, merging, and the archives-only mode: references/database.md.

## Workflow — obtaining PARSEC isochrones

PARSEC publishes no isochrone packages; tables are computed by the
official CMD web form, which stellariso drives programmatically with a
complete acquisition record of every request:

```python
from pathlib import Path

from stellariso.models.parsec.cmd_form import CmdFieldSet, CmdFormClient

client = CmdFormClient()                       # CMD 3.9 endpoint
job = client.submit(CmdFieldSet.from_overrides(isoc_isagelog=1,
                                               isoc_lagelow="9.0",
                                               isoc_lageupp="10.0",
                                               isoc_dlage="0.5"))
out = client.fetch_output(job)                 # refuses header-only tables
Path("output1.dat").write_bytes(out.content)   # archive the table
parsec = stellariso.construct("parsec/<release>", paths=["output1.dat"])
```

## Discovering names — introspect, never guess

- `facade.describe()` — identity, isochrone count, axis values.
- `grid.axes` and `grid.axis_values("log_age")` — which selection values exist.
- `sorted(iso.field_specs)` — the unified fields this product maps.
- `iso.native.columns` — the file's own columns.
- `iso.identity.label` — e.g. `mist/1.2/vvcrit0.4`.

## Out of Scope

stellariso reads and queries isochrones only. It does not analyze
evolutionary tracks, binary evolution, synthetic photometry, spectra,
population synthesis, CMD simulation, or stellar-parameter inference;
when a task needs those, say so instead of bending the isochrone API
toward them.

## Supporting Files

- `references/point-queries.md` — read before writing nontrivial query
  code: full `get`/`get_detailed` semantics, selection and
  interpolation details, phase queries, the audit record.
- `references/two-layers.md` — read when the native and unified
  layers, field mappings, parameter roles (axis/fixed/derived/
  implicit), provenance objects, or custom-coordinate interpolation
  matter.
- `references/database.md` — read before building, completing, moving,
  or merging a local database, or choosing the archives-only mode.
- `references/parsec-cmd-form.md` — read before driving the CMD form
  (field vocabulary, validation, records, politeness) or registering
  hand-obtained tables into a database.
