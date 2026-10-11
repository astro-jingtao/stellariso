# stellariso

Faithful and unified access to single-star theoretical isochrones.

`stellariso` is a provenance-first, model-agnostic Python interface for
reading, preserving, standardizing, and querying tabulated theoretical
isochrones from single-star evolution models.

## Design principles

- Preserve native model data without loss.
- Provide a traceable unified interface.
- Record all physical parameters, including fixed and derived values.
- Acquire data only as complete official packages, never as server-computed
  subsets; where a source publishes no isochrone packages, build isochrones
  locally and transparently from its official tracks.
- Record complete source chains and transformation histories.
- Avoid unsafe interpolation and silent physical assumptions.

## Scope

`stellariso` focuses on single-star theoretical isochrones.

It does not currently provide evolutionary-track analysis tools (tracks
are acquired and stored as backup data and as synthesis input),
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

PARSEC isochrones are synthesized locally from the official tracks
(PARSEC publishes track packages but no isochrone packages; its CMD web
form computes tables server-side on request, which stellariso does not
treat as a data channel):

```python
tracks = stellariso.read_parsec_tracks(
    "path/to/database/parsec/v1.2S/all_tracks/Z0.0001Y0.249.zip"
)                                                # ParsecTrackSet: one track per initial mass
isos = stellariso.synthesize_isochrones(tracks, log_ages=[9.0, 9.5, 10.0])
# isos: IsochroneSet of locally synthesized isochrones; each carries the
# transformation statement in its provenance and warns that it is a
# synthesized product, not a model-team isochrone.
parsec_iso = stellariso.ParsecIso([isos])        # ParsecIso: the same facade over them
parsec_iso.get_logg(mass=0.8, log_age=9.0)

# CMD tables downloaded by hand from the web form remain readable as-is:
parsec_cmd = stellariso.construct("parsec/v1.2S +  COLIBRI S_37 + S_35 + PR16",
                                  paths=["path/to/cmd_table.dat"])
```

The CLI form of synthesis, for use outside Python:

```bash
python tools/synthesize_parsec_isochrones.py Z0.0001Y0.249.zip \
    --log-ages 8.0,8.5,9.0,9.5,10.0 --out my_isos.dat
```

## Building a local database

There is no on-demand fetching and no implicit cache location: you build
a database once — downloading the complete published matrix (every
release, every parameter set each source offers as official packages) —
and query it fully offline, passing `database=` explicitly everywhere.

```python
# see everything that would be downloaded, with exact sizes
stellariso.build_database("path/to/database", dry_run=True)

# build it (about 49 GB for MIST: v1.2 and v2.5 isochrones + tracks;
# about 10 GB for PARSEC track archives)
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

What the sources publish (verified live 2026-10-11; all sizes exact):

- MIST: v1.2 (full + basic isochrones, vvcrit 0.0/0.4) and v2.5 (full
  isochrones, vvcrit 0.0/0.4) plus the complete EEPS track tarballs
  (30 for v1.2, 166 for v2.5) — the theory products only; the
  per-photometric-system repackages are out of scope. Upstream publishes
  no checksums; sha256 is computed at download and recorded.
- PARSEC: official static track archives — v1.2S (all compositions) and
  the v2.0 rotating / very-massive / pure-helium sets. No isochrone
  packages exist, and stellariso recognizes no isochrone channel for
  PARSEC: the CMD web form computes tables server-side on request
  (opaque, not scriptable), hence the local synthesis above.

See [docs/data-sources.md](docs/data-sources.md) for the full source
registry, verification dates, and known caveats.

## Interpolation policy

- Within one isochrone: `linear` or `pchip` along `initial_mass` (or any
  monotonic coordinate), with an audit record of the bracketing nodes and
  their phases. Extrapolation raises.
- Within one track (synthesis): linear in age between the bracketing
  models. No cross-track interpolation, no extrapolation; tracks whose
  age span does not cover the target are omitted and the omission is
  recorded. The helium-flash discontinuity is not bridged.
- Across isochrones or tracks (age, composition): **not performed**.
  Exact and nearest selection only; nearest warns and records what was
  substituted.

## Documentation

- [Architecture](docs/architecture.md) — the two-layer model, the
  registry, the database, parameters, provenance, backends.
- [Data sources](docs/data-sources.md) — verified upstream sources and
  their caveats.
- [Unified parameters](docs/unified-parameters.md) — the unified
  vocabulary and every source's mapping into it, generated from the
  registry data file.
- Physics spot-checks: `python tools/check_mist_physics.py FILE...`
  (closure relations, mass monotonicity, implied RGB Reimers efficiency).

## Tests

```bash
pytest                # offline suite (network tests deselected)
pytest -m network     # live catalog-URL checks (204 MIST + 4 PARSEC)
```

Fixtures under `tests/data/` derive from real upstream data where
possible: MIST isochrone excerpts, real trimmed PARSEC track files
(captured from the official static archive), and a documented
format-equivalent synthetic CMD table (the web form cannot be scripted).
See the fixture READMEs.
