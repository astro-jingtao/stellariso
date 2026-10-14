# The Padova CMD 3.9 web form

This document describes, completely and at the wire level, the isochrone
web form of the Padova group — the official channel through which PARSEC
isochrones are published — as verified live on 2026-10-14 and 2026-10-15.
`stellariso.models.parsec.cmd_form` (CLI: `tools/fetch_parsec_isochrones.py`)
implements exactly this protocol; [data-sources.md](data-sources.md) places
the form in the acquisition policy, and the reader that consumes the
tables is version-anchored (see [architecture.md](architecture.md)).

- Form page: `https://stev.oapd.inaf.it/cgi-bin/cmd`
- Versioned CGI endpoint (3.9): `https://stev.oapd.inaf.it/cgi-bin/cmd_3.9`
- Archived documentation per version: `https://stev.oapd.inaf.it/cmd_3.9/help.html`,
  `.../faq.html` (older versions stay reachable as `cmd_N.N`; the current
  form page was last modified upstream on 2025-11-25)
- Service maintained by L. Girardi (Osservatorio Astronomico di Padova)

## Wire protocol

A submission is a `multipart/form-data` POST to the versioned endpoint.
The response is an HTML page (job timestamps, a link to the computed
table under `/tmp/`, a retention note of about 2 h); the job itself runs
synchronously, in seconds for small requests and minutes for large grids.
The form serves scripted submissions with an honest non-browser
User-Agent — no browser emulation is needed or used.

Three protocol facts are load-bearing:

1. **The payload must be the complete current field set.** Every field
   the live form's HTML declares must be sent, with `submit_form` last.
   Incomplete payloads or stale field names are accepted and the job
   "runs", but the output contains only the header block: zero data
   rows, no error message. (The isochrone-range fields were renamed
   upstream at some point to their `isoc_`-prefixed names; payloads
   using the pre-`isoc_` vocabulary produce exactly this silent
   failure.)
2. **Checkbox/radio names must be declared in repeated `.cgifields`
   entries** (the CGI.pm convention for telling "unchecked" apart from
   "absent"), whether checked or not. The form declares 13 such names:
   `dust_sourceC`, `dust_sourceM`, `extinction_coeff`, `extinction_curve`,
   `isoc_isagelog`, `isoc_ismetlog`, `kind_LPV`, `output_gzip`,
   `output_kind`, `photsys_version`, `track_colibri`, `track_parsec`,
   `track_postagb`.
3. **Drift detection beats silence.** GET the form page before
   submitting and compare its declared control names against the
   payload; refuse zero-row outputs after download. Both guards exist
   because the server never signals a mismatch.

Output files above 50 MB are always gzipped by the server; smaller ones
are plain unless `output_gzip` is set. The output filename is
`output<N>.dat` under `/tmp/`.

## Field reference

42 control names total, grouped below as the form presents them. The
"default" is the form's own checked/initial value, which is also the
client's baseline payload.

### Evolutionary tracks

| Field | Control | Values | Default | Meaning |
|---|---|---|---|---|
| `track_parsec` | radio | `parsec_CAF09_v2.0`, `parsec_CAF09_v1.2S`, `parsec_CAF09_v1.1`, `parsec_CAF09_v1.0` | — | PARSEC track set (see the per-set table below) |
| `track_omegai` | text | 0 to 0.99 | `0.00` | initial rotation ω_i; **v2.0 only**. Selecting v2.0 turns off star-by-star extinction, the Reimers-resettable mass loss, and other features, and changes the output format (extra rotation columns) |
| `track_colibri` | radio | `parsec_CAF09_v1.2S_S_LMC_08_web`, `parsec_CAF09_v1.2S_S35`, `parsec_CAF09_v1.2S_S07`, `parsec_CAF09_v1.2S_NOV13`, `no` | — | COLIBRI TP-AGB extension (v1.2S only; `no` = PARSEC-only, no Z limitation) |
| `track_postagb` | radio | `no` | `no` | post-AGB + WD evolution: "in preparation", only `no` exists |
| `n_inTPC` | text | integer | `10` | resolution of the thermal-pulse cycles in the COLIBRI section (Marigo et al. 2017) |
| `eta_reimers` | text | float | `0.2` | RGB Reimers mass-loss efficiency η. Upstream: works fine below 0.5, check results above; **not applied for v2.0 tracks** |

Supported composition and mass ranges per set (as stated on the form):

| Set | Z range | [M/H] range | Notes |
|---|---|---|---|
| v2.0 | 0.0001–0.03 | −2.19 to +0.34 | rotation off for the lowest masses; 0.004≤Z≤0.02 from Nguyen et al. (2022), others Nguyen et al. (2025); revised 2025-10-15 |
| v1.2S | 0.0001–0.06 | −2.2 to +0.5 | 0.1≤M<350 Msun for Z≤0.02; <150 Msun for 0.03≤Z≤0.04; <20 Msun at Z=0.06 |
| v1.1 | 0.0001–0.06 | −2.2 to +0.5 | 0.1≤M<12 Msun; no COLIBRI available |
| v1.0 | 0.0005–0.07 | −1.5 to +0.6 | 0.1≤M<12 Msun; no COLIBRI available |

COLIBRI options for v1.2S with their Z validity (from the form):

- `S_LMC_08_web` (the default): the web chain — S_37 (Pastorelli 2020)
  for 0.008≤Z≤0.02, S_35 (Pastorelli 2019) for 0.0005≤Z≤0.006, PR16
  (Marigo 2013 + Rosenfield 2016) for Z≤0.0002 and Z≥0.03. This is the
  set the output header echoes as "PARSEC release v1.2S + COLIBRI
  S_37 + S_35 + PR16".
- `S35` (Pastorelli 2019), `S07` (Pastorelli 2019): limited to
  0.0005≤Z≤0.03.
- `NOV13` (Marigo 2013 + Rosenfield 2016): limited to 0.0001≤Z≤0.06.
- `no`: PARSEC tracks only, no Z limitation.

### Photometric system

| Field | Control | Values | Default | Meaning |
|---|---|---|---|---|
| `photsys_file` | select | 104 systems (list below) | `tab_mag_odfnew/tab_mag_.dat` | the photometric system file |
| `photsys_version` | radio | `YBC`, `YBCnewVega`, `odfnew` | — | bolometric-correction library: YBC (Chen et al. 2019, ATLAS9+PHOENIX mix, COMARCS giants, WM-basic/PoWR hot stars), YBC with the revised Vega SED (Bohlin et al. 2020), or `odfnew` = the older OBC library (Girardi et al. 2002, expanded through Marigo et al. 2017) |

The 104 `photsys_file` values (as declared by the captured form):

```text
YBC_tab_mag_odfnew/: tab_mag_2mass_spitzer, tab_mag_2mass_spitzer_wise, tab_mag_2mass,
  tab_mag_ogle_2mass_spitzer, tab_mag_ubvrijhk, tab_mag_bessell, tab_mag_akari, tab_mag_batc,
  tab_mag_megacam_wircam, tab_mag_wircam, tab_mag_megacam_post2014, tab_mag_megacam, tab_mag_ciber,
  tab_mag_clue_galex, tab_mag_CSST, tab_mag_decam, tab_mag_denis, tab_mag_dmc14, tab_mag_dmc15,
  tab_mag_eis, tab_mag_wfi, tab_mag_wfi2, tab_mag_euclid_nisp, tab_mag_galex_sloan, tab_mag_galex,
  tab_mag_gaia_tycho2_2mass, tab_mag_gaiaDR2_tycho2_2mass, tab_mag_gaiaDR2weiler_tycho2_2mass,
  tab_mag_gaiaEDR3, tab_mag_gaia, tab_mag_gaiaDR2, tab_mag_gaiaDR2maiz, tab_mag_gaiaDR2weiler,
  tab_mag_UVbright, tab_mag_acs_hrc, tab_mag_acs_wfc_pos04jul06, tab_mag_acs_wfc_202101,
  tab_mag_nicmosab, tab_mag_nicmosvega, tab_mag_stis, tab_mag_wfc3_wideverywide,
  tab_mag_wfc3_202101_verywide, tab_mag_wfc3_202101_medium, tab_mag_wfc3_202101_wide, tab_mag_wfpc2,
  tab_mag_hipparcos, tab_mag_int_wfc, tab_mag_iphas, tab_mag_jwst_miri_wide, tab_mag_jwst_narrow,
  tab_mag_jwst_nircam_miri_wide, tab_mag_jwst_nircam_wide, tab_mag_jwst_nircam_widemedium_dec23,
  tab_mag_jwst_nircam_widemedium_nov22, tab_mag_jwst_nircam_widemedium, tab_mag_jwst_niriss_nov22,
  tab_mag_jwst_nirspec, tab_mag_jwst_fnl, tab_mag_kepler, tab_mag_kepler_2mass, tab_mag_vst_vista,
  tab_mag_lbt_lbc, tab_mag_lsst_wfirst_proposed2017, tab_mag_noao_ctio_mosaic2, tab_mag_ogle,
  tab_mag_PLATO, tab_mag_panstarrs1, tab_mag_sloan, tab_mag_sloan_2mass, tab_mag_sloan_ukidss,
  tab_mag_swift_uvot, tab_mag_skymapper, tab_mag_spitzer, tab_mag_stroemgren, tab_mag_hsc,
  tab_mag_suprimecam, tab_mag_TESS_2mass, tab_mag_TESS_2mass_kepler, tab_mag_ukidss, tab_mag_unions,
  tab_mag_uvit, tab_mag_vertecs, tab_mag_visir, tab_mag_vista, tab_mag_vphas, tab_mag_vst_omegacam,
  tab_mag_vilnius, tab_mag_wfc3_uvisCaHK, tab_mag_washington_ddo51, tab_mag_ztf, tab_mag_deltaa
tab_mag_odfnew/: tab_mag_.dat, tab_mag_ciber2, tab_mag_acs_wfc3_nircam, tab_mag_jpas, tab_mag_lsst,
  tab_mag_lsstDP0, tab_mag_lsstR1.9, tab_mag_lsstR1.9_gaiaEDR3_euclid_Roman2024, tab_mag_Roman2021,
  tab_mag_Roman2024, tab_mag_splus, tab_mag_SuperBIT
```

### Circumstellar dust (TP-AGB only)

Affects only TP-AGB stars with significant mass loss; applied via
scaling relations (Marigo et al. 2008, Pastorelli et al. 2019) for the
Groenewegen (2006) and Bressan et al. (1998) compositions.

| Field | Values | Default |
|---|---|---|
| `dust_sourceM` (M stars) | `nodustM`, `sil` (silicates, Bressan 1998), `AlOx` (100% AlOx, Groenewegen 2006), `dpmod60alox40` (60% silicate + 40% AlOx), `dpmod` (100% silicate) | `nodustM` |
| `dust_sourceC` (C stars) | `nodustC`, `gra` (graphites, Bressan 1998), `AMC` (100% AMC), `AMCSIC15` (85% AMC + 15% SiC) | `nodustC` |

Other C-star dust options were discarded upstream starting from CMD v3.7.
`kind_dust` (hidden, `0`) is a fixed switch on the wire.

### Interstellar extinction

| Field | Control | Values | Default | Meaning |
|---|---|---|---|---|
| `extinction_av` | text | float | `0.0` | total foreground extinction A_V in mag |
| `extinction_coeff` | radio | `constant` | `constant` | coefficients computed star-by-star (constant only for the OBC/`odfnew` BC library) |
| `extinction_curve` | radio | `cardelli` | `cardelli` | Cardelli et al. (1989) + O'Donnell (1994), R_V = 3.1 |

Extinction is applied to the magnitudes only — it is a foreground screen
and leaves the physical columns unchanged: paired submissions at A_V = 0
and A_V = 1 (2026-10-15) returned 638 identical rows in every physical
column (Zini through Y) while the filter magnitudes shifted by
star-by-star Cardelli coefficients (U +1.51 to +1.57, B +1.19 to +1.33,
V +0.97 to +1.02) and `mbolmag` did not move. Upstream restrictions: it
works only for isochrone tables (not LFs or simulated populations) and
not (yet) on the PARSEC rotating models.

### Long-period variability (LPV)

| Field | Control | Values | Default | Meaning |
|---|---|---|---|---|
| `kind_LPV` | radio | `1`, `2`, `3`, `4` | `1` | period prescription (below) |

- `1` — Trabucchi et al. (2017) preliminary FM/1OM relations (backwards
  compatibility).
- `2` — Trabucchi et al. (2019): FM..4OM from linear pulsation models;
  best for overtone modes, not for the FM.
- `3` — Trabucchi et al. (2021): as 2 but the FM period and its
  dominance regime from non-linear models.
- `4` — Trabucchi et al. (2021), periods AND dominant regime from
  non-linear models; the appropriate choice for the FM (this is what
  the v1.2S header credits when selected).

`pmode` in the output gives the radial order of the dominant mode (0 =
fundamental, 1 = first overtone, ...; −1 = none expected / outside
validity). With options 2–3, low-luminosity/mass stars are mostly
assigned `pmode=4`, which upstream interprets as "only small-amplitude
oscillations, if any", not a real 4th-overtone detection.

### Initial mass function

| Field | Control | Values | Default | Meaning |
|---|---|---|---|---|
| `imf_file` | select | `tab_imf/imf_salpeter.dat`, `tab_imf/imf_chabrier_exponential.dat`, `tab_imf/imf_chabrier_lognormal.dat`, `tab_imf/imf_chabrier_lognormal_salpeter.dat`, `tab_imf/imf_kroupa_orig.dat` | `tab_imf/imf_kroupa_orig.dat` | single-star IMF |

The IMF sets the `int_IMF` column (and integrated magnitudes / LFs when
those outputs are requested): the integral of the IMF in number of
stars, normalized to 1 Msun of initially born population, from 0 up to
the current `Mini`; differences of `int_IMF` between rows give the
expected number of stars in that isochrone section per unit initial
population mass.

### Ages and metallicities

Both range families are always submitted; the mode radios select which
family the server uses. Step 0 means a single value. Up to 10^4
isochrones per submission.

| Field | Control | Default | Meaning |
|---|---|---|---|
| `isoc_isagelog` | radio `0`/`1` | `0` | age input mode: linear (yr) or log10 |
| `isoc_agelow`, `isoc_ageupp`, `isoc_dage` | text | `1.0e9`, `1.0e10`, `0.0` | linear age range and step (yr) |
| `isoc_lagelow`, `isoc_lageupp`, `isoc_dlage` | text | `6.6`, `10.13`, `0.0` | log10(age/yr) range and step (dex) |
| `isoc_ismetlog` | radio `0`/`1` | `0` | metallicity input mode: Z or [M/H] |
| `isoc_zlow`, `isoc_zupp`, `isoc_dz` | text | `0.0152`, `0.03`, `0.0` | metal mass fraction Z range and step |
| `isoc_metlow`, `isoc_metupp`, `isoc_dmet` | text | `-2`, `0.3`, `0.0` | [M/H] range and step (dex) |

Metallicity convention (form + FAQ): `[M/H] = log(Z/X) − log(Z/X)_sun`
with `(Z/X)_sun = 0.0207` and the PARSEC enrichment law
`Y = 0.2485 + 1.78 Z`. Because the solar model's *initial* surface
composition (Z=0.01774, Y=0.28) differs from its present, diffused
composition, `[M/H] = 0` yields `Z = 0.014711`, not the present-solar
`Z = 0.01524` — an intrinsic 0.015 dex zero-point offset of the initial
grid scale, documented and deliberately ignored upstream.

### Output

| Field | Control | Values | Default | Meaning |
|---|---|---|---|---|
| `output_kind` | radio | `0`, `1`, `3`, `4` | `0` | 0 = isochrone tables (stellar parameters vs initial mass); 1 = luminosity functions; 3 = simulated population of total mass `sim_mtot`; 4 = single-burst population integrated magnitudes (per 1 Msun) |
| `output_evstage` | hidden | `1` | `1` | include evolutionary-stage labels in isochrone tables |
| `lf_maginf`, `lf_magsup`, `lf_deltamag` | text | `-15`, `20`, `0.5` | | LF magnitude range (faint→bright) and bin width; counts per 1 Msun of born population, in every filter plus bolometric |
| `sim_mtot` | text | `1.0e4` | | total stellar mass of a simulated population (output kinds 3) |
| `output_gzip` | checkbox | `1` | unchecked | gzip the output file (server force-gzips above 50 MB regardless) |

Hidden fixed switches on the wire: `cmd_version` (`3.9`),
`kind_interp` (`1`), `kind_postagb` (`-1`), `kind_mag` (`2`),
`kind_dust` (`0`).

## Output format (isochrone tables, CMD 3.9)

The `#`-commented header block states the generating CMD version and
timestamp, the PARSEC + COLIBRI release chain, the adopted references,
and the physics switches actually applied (TP cycles, Reimers η, LPV
prescription, photometric system, BC library, dust, IMF, output kind).
The server's echo is authoritative over the request payload.

The real 3.9 column vocabulary (verified against server-computed
tables; note the help page's column list is stale — it still documents
`M_hec`/`logMdot`, which no real 3.9 output carries):

| Column | Meaning |
|---|---|
| `Zini` | initial metallicity of the isochrone (constant within a block) |
| `MH` | [M/H] of the isochrone on the form's zero point (see above) |
| `logAge` | log10(age/yr) |
| `Mini` | initial (age-zero) mass |
| `int_IMF` | IMF integral up to `Mini` (see IMF section) |
| `Mass` | current mass (mass-loss history applied) |
| `logL`, `logTe`, `logg` | bolometric luminosity, effective temperature, surface gravity (log10) |
| `label` | evolutionary stage (below) |
| `McoreTP` | H-exhausted core mass on the TP-AGB (0 before it; the help page's `M_hec`) |
| `C_O` | photospheric C/O (ZAMS value printed before the TP-AGB) |
| `period0`..`period4` | LPV pulsation periods per `kind_LPV` (0 = none) |
| `pmode` | dominant pulsation mode order (−1 = none) |
| `Mloss` | integrated mass lost (Msun; replaces the help page's `logMdot` rate) |
| `tau1m` | unmapped auxiliary quantity (left native) |
| `X`, `Y` | current surface H and He mass fractions (Y drifts along the isochrone; equals the initial Y = 0.2485 + 1.78 Zini at the ZAMS) |
| `Xc`, `Xn`, `Xo`, `Cexcess`, `Z` | central abundances, carbon excess, current surface Z (kept native, no unified mapping) |
| `mbolmag`, then one column per filter | absolute bolometric magnitude and the photometric system's absolute magnitudes |

Block structure: every isochrone is introduced by a repeated
column-name comment line; there are no per-block `Z=`/`Y=`/`X=` headers;
the file ends with `#isochrone terminated`. One block = one (age, Z)
isochrone; `Zini`, `MH`, `logAge` are constant within a block.

Stage labels (`label`; per the FAQ, approximate and not carefully
checked for all masses/metallicities — "don't take these labels too
seriously"): 0 = PMS; 1 = MS; 2 = SGB (or Hertzsprung gap for
intermediate/massive stars); 3 = RGB (or the quick red-giant stage for
intermediate/massive stars); 4 = core He burning (low-mass stars, or
the initial CHeB stage); 5 = CHeB, blueward Cepheid loop; 6 = CHeB,
redward Cepheid loop; 7 = EAGB (or a quick red-giant stage for massive
stars); 8 = TP-AGB; 9 = post-AGB.

Two data caveats from the FAQ: around log(age/yr) ≈ 9.15 the AGB
boosting effect produces very populated or multiple AGB sequences (a
real physical effect, not a bug); and the TP-AGB terminations carry
`label = 9` rows with `logL = −9.999` — deliberate terminator markers,
not physical points (they bound gaps in the initial-mass distribution
between TP-AGB sections).

### Layout variants (version-anchored reading)

- The layout above is what the 3.9 endpoint produces for the v1.2S
  (+COLIBRI) track sets and is what `stellariso`'s `_read_cmd_3_9`
  parser consumes; the file's own `# File generated by CMD <version>`
  echo selects the parser and unknown versions are refused loudly.
- Older CMD outputs follow the documented Girardi-readme layout
  (`log(age/yr)`, `M_ini`, `M_act`, ..., `int_IMF`, `C/O`, `M_hec`,
  `logMdot`, per-block `Z=/Y=/X=` headers, no version echo);
  `stellariso` reads those through the documented-layout parser.
- Isochrones from rotating PARSEC v2.0 tracks use a different layout
  again (surface-averaged `logTeff`/`Teff0`, `omega`, `angvel`,
  `vtaneq`, `angmon`, `Rpol`/`Req`, and per-inclination magnitudes
  `*_iXX` — see Nguyen et al. 2022 and Girardi et al. 2019); the
  anchored reader refuses them loudly rather than guessing.

## Provenance and citation

Every fetched table must be archived together with its acquisition
record: the exact ordered request payload, the endpoint and CMD
version, the job timestamps, the output URL, the file sha256, and the
server's own header echo. The FAQ's citation policy: use the references
in the output file's header (they may be incomplete — consult the
papers); if the URL itself must be cited, use
`http://stev.oapd.inaf.it/cmd`.

## Verification log

- 2026-10-11: form assessed unscriptable — later shown to be an
  artifact of stale field names (the silent-failure mode above).
- 2026-10-14: complete-field-set protocol verified with an honest
  User-Agent; single-isochrone and 3×2 age-metallicity grid tables
  retrieved; real column vocabulary established; captured fixtures
  committed under `tests/data/parsec/cmd_form/`.
- 2026-10-15: form page, help page, and FAQ captured verbatim as the
  permanent fact source for this document; field inventory (42 control
  names, 13 `.cgifields`, 104 photometric systems, 5 IMFs, 4 output
  kinds) extracted from the capture; extinction confirmed to affect
  magnitudes only (paired submissions, A_V = 0 vs 1: every physical
  column identical, filter magnitudes shifted, mbolmag unchanged).
