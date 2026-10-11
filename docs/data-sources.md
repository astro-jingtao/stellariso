# Data sources

This document records the verified upstream sources for the isochrone data
that stellariso reads. Each source entry states its class following the
priority order: model-team origin first, official archives second, scientific
archives third, third-party packages last.

All URL verifications below were performed on 2026-10-11.

## MIST

- Model family: MIST (MESA Isochrones and Stellar Tracks), based on MESA.
- Official site: https://mist.science/ (data host: waps.cfa.harvard.edu).

### Full tarballs (primary fetch channel)

| Release | Rotation | Product | URL | Status |
|---|---|---|---|---|
| v1.2 | vvcrit0.4 | full isochrones (79-col theory) | `http://waps.cfa.harvard.edu/MIST/data/tarballs_v1.2/MIST_v1.2_vvcrit0.4_full_isos.txz` | verified 200, 692,503,712 bytes |
| v1.2 | vvcrit0.4 | basic isochrones | `http://waps.cfa.harvard.edu/MIST/data/tarballs_v1.2/MIST_v1.2_vvcrit0.4_basic_isos.txz` | same URL pattern |

The tarball URL pattern is
`http://waps.cfa.harvard.edu/MIST/data/tarballs_v{version}/MIST_v{version}_vvcrit{v}_{kind}.txz`
with `kind` in `{full_isos, basic_isos}`.

### Interpolation web form (subset fetch channel)

`https://mist.science/iso_form.php` accepts a plain POST and returns an HTML
page linking a zip (`output/MIST_iso_<hash>.zip`) that contains one `.iso`
file. Verified request fields:

| Field | Example | Meaning |
|---|---|---|
| `version` | `MIST1` | MIST version selector (`MIST1` produces files whose header reads `MIST version number = 1.2`) |
| `v_div_vcrit` | `vvcrit0.4` | rotation |
| `age_scale` | `log10` | age axis units |
| `age_type` | `list` | explicit age list |
| `age_list` | `9.0 10.0` | space-separated log10(age/yr) values |
| `FeH_value` | `-1.00` | one metallicity per request |
| `alpha_value` | `p0` | [alpha/Fe] (`p0` = 0.0, solar scaled) |
| `output_option` | `theory` | theoretical columns (no photometry) |
| `output` | `UBVRIplus` | photometric system (ignored for `theory`) |
| `Av_value` | `0` | extinction (ignored for `theory`) |

Re-requests with identical parameters return row-identical `.iso` content,
so subsets fetched through the form are reproducible. The server names the
response after a hash of the request, not the content.

Note on `[Fe/H]`: the form's `[Fe/H]` request field does not map log-linearly
onto the delivered `Zinit` near solar values. The returned file header's
`Zinit` is the authoritative composition value; consumers that need a target
`Z` should verify the header after download rather than trusting the echoed
`[Fe/H]`.

### Scientific references

- Choi, J., et al. 2016, ApJ, 823, 102 (MIST models and isochrones)
- Dotter, A. 2016, ApJS, 222, 8 (MIST isochrone/EEP methodology)
- Paxton, B., et al. 2011-2018 (MESA instrument papers)

## PARSEC / Padova

- Model family: PARSEC (PAdova and TRieste Stellar Evolution Code) with the
  COLIBRI extension for the TP-AGB; isochrones are distributed through the
  CMD web interface of the Padova group.
- Official site: https://stev.oapd.inaf.it (CMD form at `/cgi-bin/cmd`).

### CMD web form (primary channel; manual use)

The CMD 3.9 form (`https://stev.oapd.inaf.it/cgi-bin/cmd_3.9`, multipart POST)
generates isochrone tables for PARSEC v2.0 (optionally rotating) and
PARSEC v1.2S + COLIBRI, over chosen age and metallicity ranges, with
photometry in a chosen photometric system. Key request fields:
`track_parsec` (track set), `track_omegai` (initial rotation for v2.0),
`isoc_isagelog` + `isoc_lagelow/isoc_lageupp/isoc_dlage` (log10 age range) or
the linear-age branch `isoc_agelow/isoc_ageupp/isoc_dage`,
`isoc_ismetlog` + `isoc_zlow/isoc_zupp/isoc_dz` (linear Z) or
`isoc_metlow/isoc_metupp/isoc_dmet` (log metallicity), `output_kind=0`
(isochrone tables), `output_evstage=1` (include the evolutionary-stage
label), `output_gzip=1`.

Results appear under `https://stev.oapd.inaf.it/tmp/output*.dat.gz` and are
deleted from the server after about 2 hours.

Current limitation: scripted submissions of this form (verified 2026-10-11
with multipart and urlencoded bodies, browser-like headers, and both the
default and explicit parameter sets) are accepted — the job runs and the
response header echoes the requested configuration — but the result file
contains only the header block and no isochrone rows. No error message is
returned. Until this changes, stellariso treats the CMD form as a
manual-download channel: the user generates the table in a browser, saves
it, and registers it as a `local_user_file` source. The reader and the
unified layer work identically on such files.

### TLS note

`stev.oapd.inaf.it` serves HTTPS with a ZeroSSL certificate whose
intermediate CA is not included in the handshake. Clients that build on
certifi will fail verification against this host. The missing intermediate
(`ZeroSSL RSA DV SSL CA 2`) is published at
`http://crt.sectigo.com/ZeroSSLRSADVSSLCA2.crt`; adding it to the trust
bundle restores full verification.

### Third-party redistributions (fallback references)

- FSPS (github.com/cconroy20/fsps) ships PARSEC isochrones in its own reduced
  column format under `ISOCHRONES/PARSEC/` (columns
  `log(age) Mini Mact logl logt logg Composition Phase`). This is a
  processed derivative, not the native CMD table; it is recorded as a
  potential third-party fallback, not as a primary source.
- No CDS/VizieR or Zenodo deposit of PARSEC isochrone tables is available
  (checked 2026-10-11 for Marigo et al. 2017 and Pastorelli et al. 2019).

### Composition conventions (from the CMD form and FAQ)

- PARSEC v1.2S tracks: scaled-solar composition following
  `Y = 0.2485 + 1.78 Z`; present-day solar metal content `Z_sun = 0.0152`.
- `[M/H] = 0` on the CMD form returns `Z = 0.014711`, not the present-solar
  `Z = 0.01524`; the offset is intrinsic to the PARSEC metallicity
  zero-point (see the CMD FAQ, which documents this behavior).

### Scientific references

- Bressan, A., et al. 2012, MNRAS, 427, 127 (PARSEC)
- Marigo, P., et al. 2013, MNRAS, 434, 488 (COLIBRI)
- Chen, Y., et al. 2014, 2015; Tang, J., et al. 2014 (extensions)
- Marigo, P., et al. 2017, ApJ, 835, 77 (PARSEC 1.2S + COLIBRI PR16 isochrones)
- Pastorelli, G., et al. 2019, 2020 (revised TP-AGB isochrones)
- Nguyen, C. T., et al. 2022, A&A, 665, A126; 2025, A&A, 701, A258
  (PARSEC v2.0 rotating tracks and isochrones)

## Format notes relevant to readers

- MIST `.iso` files: `#`-commented header; one `number of EEPs, cols` line
  per isochrone age block (usable as block boundaries); column-name line
  starts with `# EEP`; rows are whitespace-separated floats; the age of each
  row is carried by the `log10_isochrone_age_yr` column.
- CMD isochrone tables: `#`-commented header; the table lists columns such
  as `M_ini`, `M_act`, `logL/Lo`, `logTe`, `logG`, `int_IMF`, `C/O`, `M_hec`,
  `logMdot`, `label` (evolutionary stage: 0=PMS, 1=MS, 2=SGB, 3=RGB,
  4/5/6=CHEB stages, 7=EAGB, 8=TP-AGB, 9=post-AGB).
