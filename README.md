# stellariso

Faithful and unified access to single-star theoretical isochrones.

`stellariso` is a provenance-first, model-agnostic Python interface for
reading, preserving, standardizing, and querying tabulated theoretical
isochrones from single-star evolution models.

## Design principles

- Preserve native model data without loss.
- Provide a traceable unified interface.
- Record all physical parameters, including fixed and derived values.
- Retrieve data from official upstream sources whenever possible.
- Record complete source chains and transformation histories.
- Avoid unsafe interpolation and silent physical assumptions.

## Scope

`stellariso` focuses on single-star theoretical isochrones.

It does not currently provide evolutionary tracks, binary evolution,
synthetic photometry, spectra, population synthesis, CMD simulation,
or stellar-parameter inference.

## Installation

```bash
pip install .
```

Requires Python >= 3.10, numpy, astropy, scipy, and requests.

## Quick start

```python
import stellariso

# --- from files you already have (a file or a directory) ---
grid = stellariso.open_grid("path/to/MIST_v1.2_feh_p0.00_...iso", model="mist")
# model= is optional: backends sniff the sources and autodetect

# the two layers of one isochrone
iso = grid.get_isochrone(log_age=9.5)            # exact selection
iso.native["log_g"]                              # the file's own column
iso.unified["log_surface_gravity"]               # the canonical name
iso.field_info("log_surface_gravity")            # how it maps to native

# what the model actually assumed
iso.identity.label                               # 'mist/1.2/vvcrit0.4'
iso.parameter("initial_rotation")                # axis pinned at 0.4
iso.parameter("mixing_length")                   # implicit, not reported

# --- point queries through the facade ---
xx = stellariso.construct("mist", paths=["path/to/file.iso"])
xx.get_logg(mass=1.0, log_age=9.5, initial_feh=0.0)      # 4.460...
xx.get("log_effective_temperature", mass=1.0, log_age=9.5)
xx.get_phase(mass=1.0, log_age=9.5)                      # 'main_sequence'
xx.last_record                                    # bracketing nodes, phases

# PARSEC works through the same interface (local CMD tables)
pp = stellariso.construct("parsec", paths=["path/to/cmd_table.dat"])
pp.get_logg(mass=1.0, log_age=9.5, initial_z=0.0152)
```

## Fetching data

```python
# deterministic subset from the official MIST interpolation form
# (cached under $STELLARISO_DATA or ~/.stellariso; re-used, never re-fetched)
path, provenance = stellariso.fetch(
    "mist", channel="subset", feh=0.0, log_ages=[9.0, 9.5, 10.0]
)

# the complete published suite (~660 MB for MIST v1.2 vvcrit0.4 full)
path, provenance = stellariso.fetch(
    "mist", channel="tarball", version="1.2", vvcrit=0.4, kind="full_isos"
)
```

Every fetched asset carries sha256 checksums, the exact request, timestamps,
and classified source records. The cache doubles as an offline backup.
PARSEC currently has no scriptable official channel — the CMD web form
accepts scripted jobs but returns header-only tables, and no scientific
archive deposits exist — so PARSEC files are obtained through the form in a
browser and loaded from disk; `fetch("parsec", channel="manual")` explains
this. See [docs/data-sources.md](docs/data-sources.md) for the full source
registry, verification dates, and known caveats.

## Interpolation policy

- Within one isochrone: `linear` or `pchip` along `initial_mass` (or any
  monotonic coordinate), with an audit record of the bracketing nodes and
  their phases. Extrapolation raises.
- Across isochrones (age, composition): **not performed**. Exact and nearest
  selection only; nearest warns and records what was substituted.

## Documentation

- [Architecture](docs/architecture.md) — the two-layer model, parameters,
  provenance, backends.
- [Data sources](docs/data-sources.md) — verified upstream sources and their
  caveats.
- Physics spot-checks: `python tools/check_mist_physics.py FILE...` (closure
  relations, mass monotonicity, implied RGB Reimers efficiency).

## Tests

```bash
pytest                # offline suite (network tests deselected)
pytest -m network     # live acquisition smoke tests
```

Fixtures under `tests/data/` derive from real upstream files where possible
(MIST: trimmed real excerpts; PARSEC: format-equivalent synthetic tables
documented in place — real PARSEC rows could not be captured
programmatically; see the fixture READMEs).
