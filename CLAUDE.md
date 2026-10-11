# CLAUDE.md — stellariso

Agent guide for this repository. Human-facing documentation lives in the
README and the `docs/` tree; consult them before editing:

@README.md

## Project facts

- Science library: unified, provenance-first access to tabulated theoretical
  isochrones (MIST first, PARSEC second). See `docs/architecture.md` for the
  two-layer (native/unified) data model.
- All git-tracked content (code, comments, docs, commit messages) is written
  in English.
- Tests: `pytest` from the repo root; network-dependent tests are marked
  `network` and excluded from the default run via `-m "not network"` in CI
  (run them explicitly when needed).
- Test fixtures under `tests/data/` are trimmed excerpts of real upstream
  files (or documented format-equivalent synthetic tables); each carries a
  `README.md` describing its derivation. Never hand-edit fixture data.

## Conventions

- Runtime dependencies stay minimal: numpy, astropy, scipy, requests.
- No silent fallbacks: errors surface (fail clearly), and any data
  transformation must be recorded in provenance objects.
- Public API surface is re-exported from `stellariso/__init__.py`; keep the
  `__all__` list in sync.
