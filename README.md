# stellariso

Faithful and unified access to single-star theoretical isochrones.

`stellariso` is a provenance-first, model-agnostic Python interface for reading,
preserving, standardizing, and querying tabulated theoretical isochrones from
single-star evolution models.

> Status: early development. This README will grow with the package.

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
