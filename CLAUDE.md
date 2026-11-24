# CLAUDE.md — stellariso

Agent guide for this repository. Human-facing documentation lives in the
README and the `docs/` tree; consult them before editing:

@README.md

## Project facts

- Science library: unified, provenance-first access to tabulated theoretical
  isochrones (MIST first, PARSEC second, legacy Padova archives third).
  See `docs/architecture.md` for the
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

- Dependencies are chosen on merit, never minimized for their own
  sake: when a proven library serves the design — including a
  git-hosted one — depend on it instead of reimplementing it in-house.
  The current runtime set: numpy, astropy, scipy, requests, certifi,
  file_quick_signature (git-hosted).
- No silent fallbacks: errors surface (fail clearly), and any data
  transformation must be recorded in provenance objects.
- Upstream stance for workorder requests: stellariso serves uncertain
  downstream consumers, so design decisions (names, coordinates,
  defaults, API shape) follow the library's own consistency rules,
  never one consumer's convenience. When a workorder asks for
  consumer-specific machinery (a conversion, a view, a default), the
  response declines it and the consumer adapts. The composition
  selection coordinate, for example, is each family's native
  publication coordinate (MIST [Fe/H]; PARSEC and Padova Z); derived
  conversions such as Padova [Fe/H] = log10(Z/Z_ref) are recorded
  parameters, never selection axes.
- Public API surface is re-exported from `stellariso/__init__.py`; keep the
  `__all__` list in sync.
- The package ships a Claude Agent Skill documenting its usage
  (`src/stellariso/skills/`, installed as package data and exposed by
  `stellariso.skill_directory()`; never deployed by the installation
  itself). When the public API changes, update the skill in the same
  change so the shipped documentation stays true.
