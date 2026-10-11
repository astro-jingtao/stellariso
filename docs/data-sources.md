# Data sources

This document records the verified upstream sources behind a stellariso
database. Each source entry states its class following the priority
order: model-team origin first, official archives second, scientific
archives third, third-party packages last.

All URL verifications below were performed live on 2026-10-11 (every
catalog URL is re-checked by `pytest -m network`).

## Acquisition policy

- Only complete official packages are downloaded — never on-demand
  computed subsets. Anything a server computes from its models (web-form
  interpolators, the CMD isochrone generator) is treated as opaque and is
  not an acquisition channel.
- Where a source publishes tracks but no isochrone packages (PARSEC),
  isochrones are synthesized locally from the official tracks; the
  transformation is recorded in every product's provenance
  (see `stellariso.synthesis`).
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
| v1.2 | 30 × `feh_*_afe_p0.0_vvcrit{0.0,0.4}_EEPS` | evolutionary tracks (one tarball per composition/rotation) | 67–107 MB each |
| v2.5 | `vvcrit{0.0,0.4}_full_isos` | full isochrones, 84 compositions × 51 ages each | 7,579,630,000 / 7,195,356,136 B |
| v2.5 | 166 × `feh_*_afe_*_vvcrit{0.0,0.4}_EEPS` | evolutionary tracks (17 [Fe/H] × 5 [a/Fe]) | 112–187 MB each |

Rotation is published only as vvcrit 0.0 and 0.4 in every directory. Two
v2.5 EEPS links on the model-grids page (`feh_p050 × afe_p0.6`, both
rotations) are dead upstream (404) and absent from the published
directory. The per-photometric-system isochrone repackages (24 systems
for v1.2, 27 for v2.5) are excluded from the catalog: synthetic
photometry is out of scope. Raw MESA work directories live separately on
Zenodo and are not track tables.

### File formats

- Isochrone tarballs (`.txz`): one `.iso` file per composition; v1.2
  tarballs sit directly under `tarballs_v1.2/`, v2.5 one level deeper
  under `tarballs_v2.5/isos/`. `.iso` files: `#`-commented header; one
  `number of EEPs, cols` line per isochrone age block (usable as block
  boundaries); column names on the `# EEP` line; whitespace-separated
  rows; each block's age is carried by `log10_isochrone_age_yr`.
- Track tarballs (`.txz`): one directory, one file per initial mass named
  `NNNNNM.track.eep` (e.g. `00010M.track.eep` = 0.10 Msun), 77 columns
  (`star_age`, `star_mass`, `star_mdot`, `he_core_mass`, `log_L`,
  `log_Teff`, `log_R`, `log_g`, `phase`, ...) with a `#`-commented header
  stating version, MESA revision, composition, and the EEP anchor list.
  Tracks are stored as backup data; no track reader is implemented yet.
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
- Official site: https://stev.oapd.inaf.it (track database under
  `/PARSEC/`).

### Track archives (primary channel; plain static downloads)

| Archive | Contents | Size |
|---|---|---|
| `Database/PARSECv1.2/all_tracks_Pv1.2s.zip` | complete v1.2S tracks, 15 Z (0.0001–0.06) × 99 masses (0.1–350 Msun) | 265,152,329 B |
| `Database/PARSECv2.0_ROT_2025/ALL_Z_ALL_ROT.zip` | rotating v2.0 tracks, 13 Z × 7 ω/ωcrit | 5,804,662,522 B |
| `Database/PARSECv2.0_VMS/all_tracks.zip` | very-massive-star v2.0 tracks | 1,282,140,114 B |
| `Database/PARSECv2.0_PureHe/all_PureHe_tracks.zip` | pure-helium v2.0 tracks | 891,751,421 B |

Per-composition sub-zips exist for each (e.g. `Z0.0001Y0.249.zip`); the
all-in-one archives are what the catalog acquires. v1.2S is the product
stellariso reads and synthesizes; the v2.0 formats (95-column, no PHASE
column; very-low-mass entries keep the old 22-column subset) are
downloaded as data with no reader yet.

Track file format (v1.2S, per the official
`Database/PARSECv1.2/readme.html`): one plain-text file per initial mass,
one header line of 24 column names, then whitespace-separated rows:
`MODELL MASS AGE LOG_L LOG_TE LOG_R LOG_RAT M_CORE_HE M_CORE_C H_CEN
HE_CEN C_cen O_cen LX LY LC LNEUTR L_GRAV H_SUP HE_SUP C_SUP N_SUP O_SUP
PHASE`. `MODELL` is a model counter; `MASS` is the stellar mass in
Msun; `AGE` is in years; `LOG_R` is log10(R/cm); there is no gravity
column (stellariso derives log g from MASS and LOG_R with documented
constants). `LOG_RAT` uses a −30 sentinel for "no mass loss". The single
`*ADD.DAT` file per zip is discarded (official instruction); `*.HB.DAT`
files are post-helium-flash horizontal-branch tracks whose PHASE
numbering restarts with its own meaning. The readme names PHASE but
enumerates no codes; stellariso's code table (see
[unified-parameters](unified-parameters.md)) is derived from the physical
state at each integer transition and says so.

### Rejected channel: CMD web form

The CMD 3.9 form (`https://stev.oapd.inaf.it/cgi-bin/cmd_3.9`, multipart
POST) computes isochrone tables server-side on request for PARSEC v2.0
(optionally rotating) and PARSEC v1.2S + COLIBRI over chosen
age/metallicity ranges. It is rejected as an acquisition channel on both
grounds of the policy above: the tables are produced by opaque
server-side computation, and the form cannot be scripted — submissions
(verified 2026-10-11 with multipart and urlencoded bodies, browser-like
headers, and both default and explicit parameter sets) are accepted and
the response echoes the configuration, but the result file contains only
the header block and zero isochrone rows, with no error. PARSEC is
therefore a tracks-only source for stellariso: local synthesis from the
official tracks (see `stellariso.synthesis`) is the isochrone source. A
table a user downloads by hand in a browser remains fully readable as a
local user file (`construct("parsec/<release>", paths=[...])`,
`local_user_file` provenance) — read support, not acquisition.

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
- No CDS/VizieR or Zenodo deposit of PARSEC track or isochrone tables
  exists (checked 2026-10-11; the only Zenodo hits are third-party
  interpolated subsets). `pleiadi.oapd.inaf.it` hosts historical
  (pre-2006/07) tracks only.

### Composition conventions (from the CMD form and FAQ)

- PARSEC v1.2S tracks: scaled-solar composition following
  `Y = 0.2485 + 1.78 Z`; present-day solar metal content `Z_sun = 0.0152`.
  The track zips state Z and Y directly in their names (e.g.
  `Z0.0001Y0.249`) — the authoritative values.
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
  (PARSEC v2.0 rotating tracks and isochrones)
- Costa, G., et al. 2025 (v2.0 very-massive-star and pure-He tracks)

## Format notes relevant to readers

- MIST `.iso` files: `#`-commented header; one `number of EEPs, cols`
  line per isochrone age block; column-name line starts with `# EEP`;
  rows are whitespace-separated floats; the age of each row is carried by
  the `log10_isochrone_age_yr` column.
- PARSEC v1.2S track `.DAT` files: see the track file format paragraph
  above; the initial mass is stated by the filename
  (`..._M<mass:7.3f>.DAT`), not by a column.
- CMD isochrone tables: `#`-commented header; columns such as `M_ini`,
  `M_act`, `logL/Lo`, `logTe`, `logG`, `int_IMF`, `C/O`, `M_hec`,
  `logMdot`, `label` (evolutionary stage: 0=PMS, 1=MS, 2=SGB, 3=RGB,
  4/5/6=CHEB stages, 7=EAGB, 8=TP-AGB, 9=post-AGB).
