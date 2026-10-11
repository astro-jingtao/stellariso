# PARSEC test fixtures

## `parsec_cmd_v1p2S_fixture.dat`

A format-equivalent synthetic CMD isochrone table — parser test data, NOT
science data.

- Why synthetic: the CMD 3.9 web form currently returns header-only results
  to scripted submissions (verified 2026-10-11; `docs/data-sources.md`), so
  no real data rows could be captured programmatically, and no CDS/VizieR or
  Zenodo deposit of PARSEC isochrone tables exists to draw from.
- Header block: verbatim from a real CMD 3.9 server response for a
  PARSEC v1.2S + COLIBRI S_37 + S_35 + PR16, UBVRIJHK, no-extinction request
  (2026-10-11).
- Column layout: the documented format — Girardi isochrone readme
  "TABLES OF ISOCHRONES" section
  (`pleiadi.oapd.inaf.it/isoc_photsys.02/readme.txt`) plus the CMD 3.9
  updates stated on the official help page (FLUM replaced by `int_IMF`;
  `C/O`, `M_hec`, `logMdot`, `label` added). Columns: `log(age/yr) M_ini
  M_act logL/Lo logTe logG label U B V R I J H K int_IMF C/O M_hec logMdot`
  (19 columns).
- Data rows: hand-computed with `make_parsec_fixture.py` (same directory) —
  plausible monotone mass-luminosity-temperature relations, two isochrones
  (log10(age/yr) = 9.0 and 9.5, 40 rows each) at Z = 0.0152 with
  Y = 0.2485 + 1.78 Z, per-isochrone header lines carrying Z/Y/X/age in the
  documented "HEADER LINE" style.
- When a real CMD table with data rows becomes available (manual browser
  download works today), the fixture should be replaced by a trimmed real
  excerpt following the MIST fixture pattern (`tests/data/mist/README.md`),
  and the parser re-verified against it.
