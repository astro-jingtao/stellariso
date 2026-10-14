# Data sources

This document records the verified upstream sources behind a stellariso
database. Each source entry states its class following the priority
order: model-team origin first, official archives second, scientific
archives third, third-party packages last.

All URL verifications below were performed live on 2026-10-11 (every
catalog URL is re-checked by `pytest -m network`).

## Acquisition policy

- Data is acquired as the source publishes it. Where a source offers
  complete official packages, those packages — the whole published matrix
  — are downloaded, never hand-picked subsets of them.
- Where a source's only isochrone channel is an official computation
  service (the PARSEC CMD web form), that service is driven
  programmatically and every table is archived with its complete
  acquisition record: the exact ordered request payload, the server's own
  header echo, checksums, and timestamps.
- Upstreams publish no checksums for any of the packages below; sha256 is
  computed at download time and recorded in each MANIFEST, so database
  contents are verifiable forever after.

## MIST

- Model family: MIST (MESA Isochrones and Stellar Tracks), based on MESA.
- Official site: https://mist.science/ — the canonical data host. The
  historical host `waps.cfa.harvard.edu/MIST/data/` still resolves but is
  a 302 alias of `https://mist.science/data/` (verified 2026-10-11); the
  catalog uses the canonical URLs.
- `/data/` holds exactly two version directories: `tarballs_v1.2/` and
  `tarballs_v2.5/` (no v1.0/v1.1/v2.0 tarballs exist; the older links on
  the resources page are dead upstream).

### Published packages (all HEAD-verified 200; exact sizes in the catalog)

| Release | Product | Contents | Size |
|---|---|---|---|
| v1.2 | `vvcrit{0.0,0.4}_full_isos` | full isochrones (79-col theory), 15 [Fe/H] × 107 ages each | 692,503,712 / 628,221,896 B |
| v1.2 | `vvcrit{0.0,0.4}_basic_isos` | basic isochrones (25-col), 15 [Fe/H] × 107 ages each | 221,507,784 / 217,044,928 B |
| v2.5 | `vvcrit{0.0,0.4}_full_isos` | full isochrones, 84 compositions × 51 ages each | 7,579,630,000 / 7,195,356,136 B |

Rotation is published only as vvcrit 0.0 and 0.4 in every directory. The
per-photometric-system isochrone repackages (24 systems for v1.2, 27 for
v2.5) and the EEPS evolutionary-track tarballs are excluded from the
catalog: synthetic photometry is out of scope and stellariso consumes
isochrone products only. Raw MESA work directories live separately on
Zenodo and are not track tables.

### File formats

- Isochrone tarballs (`.txz`): one `.iso` file per composition; v1.2
  tarballs sit directly under `tarballs_v1.2/`, v2.5 one level deeper
  under `tarballs_v2.5/isos/`. `.iso` files: `#`-commented header; one
  `number of EEPs, cols` line per isochrone age block (usable as block
  boundaries); column names on the `# EEP` line; whitespace-separated
  rows; each block's age is carried by `log10_isochrone_age_yr`.
- The EEPS track tarballs (`.txz`, one `NNNNNM.track.eep` file per
  initial mass) are out of scope: stellariso catalogs isochrone products
  only; no track reader exists.
- Bolometric-correction tables are published separately under
  `data/BC_tables/v1/*` and `v2/*` (out of scope).

### Rejected channel: interpolation web form

`https://mist.science/iso_form.php` accepts a plain POST and returns a
zip with one `.iso` covering requested (version, rotation, [Fe/H],
[a/Fe], age list). It functions (verified end-to-end 2026-10-11), but the
delivered isochrones are computed server-side by the form's own
interpolation machinery — opaque to this library — so it is not an
acquisition channel. The published tarballs contain the same model data
produced by the model team's own pipeline.

### Scientific references

- Choi, J., et al. 2016, ApJ, 823, 102 (MIST models and isochrones)
- Dotter, A. 2016, ApJS, 222, 8 (MIST isochrone/EEP methodology)
- Paxton, B., et al. 2011-2018 (MESA instrument papers)

## PARSEC / Padova

- Model family: PARSEC (PAdova and TRieste Stellar Evolution Code) with
  the COLIBRI extension for the TP-AGB.
- Official site: https://stev.oapd.inaf.it.

### CMD web form (the isochrone channel)

PARSEC publishes no isochrone packages. Its isochrones are computed by
the official CMD web form (`https://stev.oapd.inaf.it/cgi-bin/cmd`,
multipart POST to the versioned endpoint `/cgi-bin/cmd_3.9`), which
stellariso drives programmatically through the request-layer client
`stellariso.models.parsec.cmd_form` (CLI:
`tools/fetch_parsec_isochrones.py`). The form's complete wire-level
documentation — every field, output layout, protocol pitfalls — is
[cmd-form.md](cmd-form.md).

The form is scriptable — verified live 2026-10-14 with an honest
non-browser User-Agent — under a strict wire protocol the client encodes:

- The payload must be the COMPLETE current field set: every field the
  live form's HTML declares, the isochrone-range fields under their
  `isoc_`-prefixed names, every checkbox name additionally declared in
  repeated `.cgifields` entries (the CGI.pm unchecked-vs-absent
  protocol), and `submit_form` last. Payloads with stale field names or
  missing fields are accepted and run without any error but return
  header-only tables — zero data rows (the silent failure mode the
  client guards against at payload validation, live-form drift check,
  and zero-row refusal).
- One submission can request a whole age × metallicity grid
  (`isoc_lagelow/lageupp/dlage`, `isoc_metlow/metupp/dmet` ranges); the
  job runs synchronously (seconds to minutes) and the result page links
  the table under `/tmp/` with about 2 h retention.
- The output table's `#` header echoes the release chain (e.g.
  "isochrones based on PARSEC release v1.2S +  COLIBRI S_37 + S_35 +
  PR16"), the CMD version, and the physics switches; the client archives
  that echo together with the exact ordered payload, timestamps, and the
  file's sha256 in a sidecar acquisition record.

The PARSEC track archives are out of scope: isochrones are acquired as
the model team's own form computes them, which is closer to the
published product than any local reconstruction from tracks.

### TLS note

`stev.oapd.inaf.it` serves HTTPS with a ZeroSSL certificate whose
intermediate CA (`ZeroSSL RSA DV SSL CA 2`, issued by Sectigo's R46 root,
valid to 2035) is missing from the handshake. The genuine intermediate is
bundled with the package (`models/parsec/ZeroSSLRSADVSSLCA2.crt`) and
appended to the standard trust store at build time — certificate
verification stays on; it is never disabled.

### Third-party redistributions (fallback references)

- FSPS (github.com/cconroy20/fsps) ships PARSEC isochrones in its own
  reduced column format under `ISOCHRONES/PARSEC/`. This is a processed
  derivative, not the native product; recorded as a potential third-party
  fallback, not as a primary source.
- No CDS/VizieR or Zenodo deposit of PARSEC isochrone tables exists
  (checked 2026-10-11; the only Zenodo hits are third-party interpolated
  subsets). `pleiadi.oapd.inaf.it` hosts historical (pre-2006/07) tracks
  only.

### Composition conventions (from the CMD form and FAQ)

- PARSEC v1.2S: scaled-solar composition following
  `Y = 0.2485 + 1.78 Z`; present-day solar metal content `Z_sun = 0.0152`.
- `[M/H] = 0` on the CMD form returns `Z = 0.014711`, not the
  present-solar `Z = 0.01524`; the offset is intrinsic to the PARSEC
  metallicity zero-point (documented in the CMD FAQ).

### Scientific references

- Bressan, A., et al. 2012, MNRAS, 427, 127 (PARSEC)
- Chen, Y., et al. 2014, MNRAS, 444, 2525 (low masses down to 0.1 Msun)
- Tang, J., et al. 2014 (massive stars up to ~350 Msun)
- Chen, Y., et al. 2015, MNRAS, 452, 1068; Fu, X., et al. 2018, MNRAS,
  476, 496 (v1.2S revisions)
- Marigo, P., et al. 2013, MNRAS, 434, 488 (COLIBRI)
- Marigo, P., et al. 2017, ApJ, 835, 77 (PARSEC 1.2S + COLIBRI PR16 isochrones)
- Pastorelli, G., et al. 2019, 2020 (revised TP-AGB isochrones)
- Nguyen, C. T., et al. 2022, A&A, 665, A126; 2025, A&A, 701, A258
  (PARSEC v2.0, rotating)

## Format notes relevant to readers

- MIST `.iso` files: `#`-commented header; one `number of EEPs, cols`
  line per isochrone age block; column-name line starts with `# EEP`;
  rows are whitespace-separated floats; the age of each row is carried by
  the `log10_isochrone_age_yr` column.
- CMD 3.9 isochrone tables (the layout real outputs use): `#`-commented
  header whose first line states the CMD version; per-row columns `Zini`
  `MH` `logAge` `Mini` `int_IMF` `Mass` `logL` `logTe` `logg` `label`
  (stage: 0=PMS, 1=MS, 2=SGB, 3=RGB, 4/5/6=CHEB stages, 7=EAGB, 8=TP-AGB,
  9=post-AGB) `McoreTP` `C_O` ... plus the photometric magnitudes; every
  isochrone block is introduced by a repeated column-name comment line and
  the file ends with `#isochrone terminated`.
- Older CMD isochrone tables (the documented Girardi-readme layout, no
  version echo): `log(age/yr)`, `M_ini`, `M_act`, `logL/Lo`, `logTe`,
  `logG`, magnitudes, `int_IMF`, `C/O`, `M_hec`, `logMdot`, with
  per-isochrone `Z=/Y=/X=` block headers. Reading is version-anchored:
  the file's own version echo selects the parser; both layouts are
  accepted, and no layout is guessed for an unanchored file.
