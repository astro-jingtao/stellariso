# stellariso

Faithful and unified access to single-star theoretical isochrones.

`stellariso` is a provenance-first, model-agnostic Python interface for
reading, preserving, standardizing, and querying tabulated theoretical
isochrones from single-star evolution models.

## Design principles

- Preserve native model data without loss.
- Provide a traceable unified interface.
- Record all physical parameters, including fixed and derived values.
- Acquire data as the source publishes it: complete official packages where
  they exist, and — where a source's only isochrone channel is an official
  computation service (the PARSEC CMD web form) — that service, driven
  programmatically with a complete acquisition record of every request.
- Record complete source chains and transformation histories.
- Avoid unsafe interpolation and silent physical assumptions.

## Scope

`stellariso` focuses on single-star theoretical isochrones.

It does not provide evolutionary-track analysis tools,
binary evolution, synthetic photometry, spectra, population synthesis,
CMD simulation, or stellar-parameter inference.

## Installation

```bash
pip install .
```

Requires Python >= 3.10, numpy, astropy, scipy, and requests.

## Quick start

```python
import stellariso

# --- opening files you already hold (a file or a directory) ---
grid = stellariso.open_grid("path/to/MIST_v1.2_feh_p0.00_...iso", model="mist/1.2")
# grid: IsochroneGrid — every isochrone in the product, queryable by grid point.
# model= is optional: backends sniff the sources and autodetect; when given,
# it is version-qualified ("mist/1.2") and validated against the files.

# the two layers of ONE isochrone
iso = grid.get_isochrone(log_age=9.5, initial_feh=0.0)  # Isochrone: one age+composition slice of the grid
iso.native["log_g"]                              # the file's own column
iso.unified["log_surface_gravity"]               # the canonical name
iso.field_info("log_surface_gravity")            # how it maps to native

# what the model actually assumed
iso.identity.label                               # 'mist/1.2/vvcrit0.4'
iso.parameter("initial_rotation")                # axis pinned at 0.4
iso.parameter("mixing_length")                   # implicit, not reported

# --- point queries through the facade ---
# The "facade" is the single front-end object per model product
# (UnifiedIso; MistIso/ParsecIso are its per-family implementations):
# it wraps one whole grid and answers single-star queries directly,
# combining grid-point selection with within-isochrone interpolation
# so you never touch the two-layer machinery for a quick number.
mist_iso = stellariso.construct("mist/1.2", paths=["path/to/file.iso"])
# mist_iso: MistIso — a point-query facade over the WHOLE grid (an
# IsochroneGrid subclass), not a single isochrone; `iso` above is one slice.
mist_iso.get_logg(mass=1.0, log_age=9.5, initial_feh=0.0)   # 4.460...
mist_iso.get("log_effective_temperature", mass=1.0, log_age=9.5, initial_feh=0.0)
mist_iso.get_phase(mass=1.0, log_age=9.5, initial_feh=0.0)  # 'main_sequence'
mist_iso.last_record                                        # bracketing nodes, phases
```

PARSEC publishes no isochrone packages; its isochrones are computed by the
official CMD web form, which stellariso drives programmatically
(`stellariso.models.parsec.cmd_form` — every submission archives the exact
ordered payload, the server's own header echo, and the file checksum):

```python
from stellariso.models.parsec.cmd_form import CmdFieldSet, CmdFormClient

client = CmdFormClient()                          # CMD 3.9 endpoint
job = client.submit(CmdFieldSet.from_overrides(isoc_isagelog=1,
                                               isoc_lagelow="9.0",
                                               isoc_lageupp="10.0",
                                               isoc_dlage="0.5"))
out = client.fetch_output(job)                     # refuses header-only tables
out.record()                                       # full acquisition record

# the downloaded table reads like any other isochrone product:
parsec_iso = stellariso.construct("parsec/v1.2S +  COLIBRI S_37 + S_35 + PR16",
                                  paths=["path/to/output1.dat"])
parsec_iso.get_logg(mass=0.8, log_age=9.0)
```

The CLI form of fetching, for use outside Python:

```bash
python tools/fetch_parsec_isochrones.py \
    --isoc_isagelog 1 --isoc_lagelow 9.0 --isoc_lageupp 10.0 --isoc_dlage 0.5 \
    [--out my_isos.dat]
```

## Building a local database

There is no implicit cache location: you build a database once —
downloading the complete published matrix where the source publishes
packages (MIST), and computing the declared products through the
source's official form where that is the only channel (PARSEC) — and
query it fully offline afterwards, passing `database=` explicitly
everywhere. Re-running the build completes whatever is missing; already
verified products are never re-fetched (or re-computed).

```python
# see everything that would be downloaded, with exact sizes
stellariso.build_database("path/to/database", dry_run=True)

# build it (about 16.5 GB for the MIST isochrone products)
db = stellariso.build_database("path/to/database")

# query it offline, by version-qualified model
db = stellariso.open_database("path/to/database")
mist_iso = stellariso.construct("mist/1.2", database=db,
                                label="vvcrit0.4_full_isos")
```

Every product directory keeps the downloaded archive, the extracted
files, and a `MANIFEST.json` recording the exact URL, sha256, size,
retrieval time, file-format notes, and the literature to cite; the
database root carries an inventory (`database.json`), a human `README.md`
with format notes and citations, and a snapshot of the
[unified-parameters](docs/unified-parameters.md) documentation. The
database is therefore self-contained — with both model websites gone, the
data and its meaning remain interpretable — and portable: the whole
database, or any subset of its product directories, can be copied to
another machine and opened there. Verified products are never
re-downloaded; re-running the build completes whatever is missing.

What the sources publish (verified live 2026-10-11/10-15; all sizes exact):

- MIST: v1.2 (full + basic isochrones, vvcrit 0.0/0.4) and v2.5 (full
  isochrones, vvcrit 0.0/0.4) — the isochrone theory products; the
  per-photometric-system repackages and the EEPS track tarballs are out
  of scope. Upstream publishes no checksums; sha256 is computed at
  download and recorded.
- PARSEC: no isochrone packages exist. The official CMD web form computes
  isochrone tables server-side on request and is scriptable when given
  the complete current field set (verified 2026-10-14); the catalog
  declares its full product matrix — 206 tables across every track-set
  combination the form accepts, on a 0.1 dex metallicity grid over each
  set's full range and fine log-age grids (0.02 dex for the current
  sets), plus one product per auxiliary option value. Every table is
  archived with its exact payload and the server's own header echo.

See [docs/data-sources.md](docs/data-sources.md) for the full source
registry, verification dates, and known caveats.

## Interpolation policy

- Within one isochrone: `linear` or `pchip` along `initial_mass` (or any
  monotonic coordinate), with an audit record of the bracketing nodes and
  their phases. Extrapolation raises.
- Across isochrones (age, composition): **not performed**.
  Exact and nearest selection only; nearest warns and records what was
  substituted.

## Documentation

- [Architecture](docs/architecture.md) — the two-layer model, the
  registry, the database, parameters, provenance, backends.
- [Data sources](docs/data-sources.md) — verified upstream sources and
  their caveats.
- [The CMD 3.9 web form](docs/cmd-form.md) — the complete wire-level
  documentation of the PARSEC isochrone form: every field, the output
  formats, and the protocol pitfalls.
- [The PARSEC acquisition blueprint](docs/parsec-blueprint.md) — the
  declared full design of the form-computed database: cells, grids,
  fixed parameters, fetch tiers, and the completion-report tool.
- [Unified parameters](docs/unified-parameters.md) — the unified
  vocabulary and every source's mapping into it, generated from the
  registry data file.
- Physics spot-checks: `python tools/check_mist_physics.py FILE...`
  (closure relations, mass monotonicity, implied RGB Reimers efficiency).

## Tests

```bash
pytest                # offline suite (network tests deselected)
pytest -m network     # live catalog-URL checks (6 MIST) + one live CMD form job
```

Fixtures under `tests/data/` derive from real upstream data where
possible: MIST isochrone excerpts and CMD form captures (result page,
real table excerpt, empty-table failure shape). See the fixture READMEs.
