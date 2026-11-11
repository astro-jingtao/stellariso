# Padova test fixtures

Trimmed excerpts of the two legacy Padova VizieR archives, kept
whole-isochrone by whole-isochrone: every retained row is verbatim from
the original files, no value is altered, and within a kept isochrone
every row is kept (the characteristic-point anchors and shape features
the phase-classification rules read must stay intact).

## Originals

Both directories fetched from the ADAC mirror's native VizieR tree
(plain HTTP, no checksums upstream — sha256 computed at download):

- `http://vizier.nao.ac.jp/ftp/cats/J/A+AS/106/275/` (Bertelli et al.
  1994, padova/1994), verified live 2026-11-10 and 2026-11-12;
  `table1.gz` sha256
  `4c43fe832694e2041e8b71bf750772ba672cf61a44d18111adec294b079d067f`
  (121,897 B); `table5.gz` sha256
  `1c49e7d119ae2a3d96b0acd6001b642be956644dcb1cd63b1c4f25b7d90376be`
  (132,222 B) —
  see `.ref/recon/2026-11-10-vizier-j-a-as-106-275-padova1994.md` for
  the full per-file list (the full sha256 values live there; the two
  above are reproduced from it and re-verified 2026-11-12).
- `http://vizier.nao.ac.jp/ftp/cats/J/A+AS/141/371/` (Girardi et al.
  2000, padova/2000), same verification dates;
  `isochron.dat.gz` sha256
  `635451374979c4955f3ef6a3fa1fb83eaec56b60356b7a0b1b02186b1b15d61c`
  (2,894,512 B) — full list in
  `.ref/recon/2026-11-10-vizier-j-a-as-141-371-padova2000.md`.

## Contents

- `p2000/isochron.dat` + `p2000/isochsum.dat`: five isochrones —
  (Overshoot=1, Z=0.019, log(age)=9.00), (1, 0.019, 10.00),
  (0, 0.019, 9.00), (1, 0.004, 9.00), (1, 0.019, 7.80); the summary
  keeps exactly those five isochrones' characteristic points. Covers
  the Overshoot axis, two metallicities, a TP-AGB-ending old
  isochrone, and a C-ignition-ending young one.
- `p1994/table5` (Z=0.02, Y=0.28): blocks log(age) = 6.70 (youngest
  massive block, Wolf-Rayet rows), 7.00 (Mwind>0 rows), 9.00 (one mass
  jump), 10.00 (two mass jumps; the post-AGB/WD tail).
- `p1994/table1` (Z=0.0004, Y=0.23): block log(age) = 9.50.

The canonical file names (`isochron.dat`, `isochsum.dat`, `table1`,
`table5`) are load-bearing: the padova/1994 reader assigns each
table's (Z, Y) from the catalog ReadMe's documented file list, so the
fixtures must keep those names.

## Regenerate

Download the originals (URLs above) into `<src>/j106275/` and
`<src>/j141371/`, then:

    python make_padova_fixtures.py <src> tests/data/padova
