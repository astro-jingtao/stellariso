# PARSEC v1.2S track fixture (real data, trimmed)

Real excerpts of the official PARSEC v1.2S track archive — unlike the CMD
isochrone-table fixture (synthetic, because the web form cannot be
scripted), the track archives are static downloads, so real rows could be
captured programmatically.

- Source zip: `Z0.0001Y0.249.zip` (sha256 in `SOURCE.txt`), from
  https://stev.oapd.inaf.it/PARSEC/Database/PARSECv1.2/ (verified live
  2026-10-11; downloaded through the official per-metallicity download
  link).
- Files kept (verbatim names, note the OUTA overshoot prefix differs per
  mass range):
  - `M000.600.DAT` (OUTA1.77), `M000.800.DAT`, `M001.000.DAT` (OUTA1.74)
    — standard tracks, initial masses 0.6 / 0.8 / 1.0 Msun;
  - `M0.700.HB.DAT` — horizontal-branch (post-flash) track;
  - `M060.000ADD.DAT` — an ADD merge file, kept so the discard path is
    exercised against real data.
- Row trimming (`make_parsec_track_fixture.py`): first and last model of
  each track, every model where `floor(PHASE)` changes, and every 20th
  model in between. Header lines and column values are untouched; no rows
  were modified.
- Regenerate with
  `python make_parsec_track_fixture.py <path-to-Z0.0001Y0.249.zip>`.
