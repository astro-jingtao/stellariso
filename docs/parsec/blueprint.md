# The PARSEC form-product acquisition blueprint

This document declares the complete design of the form-computed half of
a stellariso database: every product cell that will exist when the
PARSEC build is finished, at which parameter values, and with which
fixed settings. The machine-readable carrier is
`stellariso.models.parsec.blueprint` (tests:
`tests/parsec/test_blueprint.py`); `tools/parsec/blueprint_status.py` measures
any database against it and reports what is complete, what is pending,
and what must be re-fetched. The wire protocol the submissions speak is
documented in [cmd-form.md](cmd-form.md); this page fixes what is sent
and why, not how.

## Design principles

- **One uniform fine design.** There are no coarse products. Every
  track set — current or historical — is designed at the same fine age
  spacing and the same 0.1 dex composition grid. What varies between
  sets is only *when* their cells are fetched, never how the cells are
  designed.
- **Design is separate from fetch order.** Primary sets (the two
  current physics chains) are fetched at full design extent. Secondary
  sets (older chains and alternative COLIBRI options) are fetched
  sparsely first — a subset of the same designed cells — and can be
  completed later, cell by cell, without any redesign.
- **All combinations are traversed.** Every (track set, [M/H],
  initial rotation) point the form accepts is a cell of the design,
  including exact window boundaries and every rotation value.
- **Nothing that leaves the isochrone unchanged is varied.** The IMF,
  the photometric system, and interstellar extinction change only
  auxiliary or magnitude columns (verified: extinction shifts filter
  magnitudes and leaves every physical column untouched; the IMF scales
  only `int_IMF`). They stay at the canonical baseline below, recorded
  in full in every archived payload, so any variant can still be
  computed on demand later.
- **Every submission is the complete field set.** The form's CGI
  silently returns empty tables for partial payloads, so each request
  carries all 42 fields; the archived `request_fields` of every product
  therefore pins a payload that replays the identical request
  (`CmdFieldSet.from_mapping(record["request_fields"])`), including the
  values of fields that were not varied.

## The cell space

A **cell** is one (track set, [M/H], ω_i) point. Each cell is one
directory in the database holding two archived submissions: the
log-age table `output.dat` and the linear-age refinement
`output_linear.dat`, each with its own acquisition record. Cell count
per set (full design):

| Set (directory) | Tier | Tracks | [M/H] window | ω_i | Cells |
|---|---|---|---|---|---|
| `v1.2S_COLIBRI_web` | primary | v1.2S + COLIBRI web chain (`S_LMC_08_web`) | −2.2 … +0.5 (stated) | 0 fixed | 28 |
| `v2.0` | primary | v2.0 (no COLIBRI option exists for it) | −2.19 … +0.34 (stated) | 0 … 0.9 step 0.1, plus 0.99 | 297 = 27 × 11 |
| `v1.2S_COLIBRI_S35` | secondary | v1.2S + COLIBRI S_35 | −1.4921 … +0.3363 (Z 0.0005–0.03 converted) | 0 fixed | 20 |
| `v1.2S_COLIBRI_S07` | secondary | v1.2S + COLIBRI S_07 | −1.4921 … +0.3363 (Z 0.0005–0.03 converted) | 0 fixed | 20 |
| `v1.2S_COLIBRI_PR16` | secondary | v1.2S + COLIBRI PR16 (`NOV13`) | −2.2 … +0.5 (stated) | 0 fixed | 28 |
| `v1.2S_no_colibri` | secondary | v1.2S, no TP-AGB extension | −2.2 … +0.5 (stated) | 0 fixed | 28 |
| `v1.1` | secondary | v1.1 (no COLIBRI) | −2.2 … +0.5 (stated) | 0 fixed | 28 |
| `v1.0` | secondary | v1.0 (no COLIBRI) | −1.5 … +0.6 (stated) | 0 fixed | 22 |

Full design: **471 cells** — 325 primary (28 + 297), 146 secondary —
and **942 submissions** (two age grids per cell). Which COLIBRI chain
each option is: the web chain applies S_37 (Pastorelli 2020) for
0.008≤Z≤0.02, S_35 (Pastorelli 2019) for 0.0005≤Z≤0.006, and PR16
(Marigo 2013 + Rosenfield 2016) outside those ranges, which is what the
output header echoes as "v1.2S + COLIBRI S_37 + S_35 + PR16"; PARSEC
v2.0 is submitted with `track_colibri=no` — COLIBRI is a v1.2S-only
option, and the v2.0 echo names only "PARSEC release v2.0" (Costa et
al. 2019a,b code; Nguyen et al. 2022, 2025 tracks).

## The grids

**Composition.** Steps of 0.1 dex across each set's full valid window,
plus the exact window edges whenever they do not fall on the 0.1 dex
grid. Window provenance: where the form states a [M/H] range for the
set (v2.0: −2.19…+0.34; v1.2S and v1.1: −2.2…+0.5; v1.0: −1.5…+0.6),
those stated numbers are the edges — they are the server's own
acceptance range. The COLIBRI S_35/S_07 options are stated in Z only
(0.0005≤Z≤0.03); their edges are converted through the form's own
enrichment law (Y = 0.2485 + 1.78 Z, (Z/X)_☉ = 0.0207) to [M/H]
−1.4921 and +0.3363. The PR16 option's Z range (0.0001–0.06) converts
to [−2.1917, +0.6953], which does not narrow the stated v1.2S window —
an upstream inconsistency resolved in favor of the stated window, which
the server demonstrably serves across the full range. So: v2.0 carries
27 compositions (25 grid steps −2.1…+0.3 plus the edges −2.19 and
+0.34), S_35/S_07 carry 20 (18 grid steps plus two converted edges),
and the stated-window sets carry their on-grid edge-to-edge count (28,
28, 28, 28, 22).

**Initial rotation.** ω_i from 0 to 0.9 in steps of 0.1, plus 0.99 —
11 values. The form offers rotation for v2.0 only (0 ≤ ω_i ≤ 0.99,
single text field `track_omegai`), the server interpolates isochrones
between track rotation values (form news, 2024-10-01), and the header
echo states the applied value ("Rotating tracks computed with
omega_i=…"). ω = 0 reproduces the non-rotating v2.0 tables; every
other set is fixed at ω = 0 and its payload records that.

**Ages — log grid.** log10(age/yr) from 6.6 to 10.13 in steps of
0.02 dex, identical for every set: 177 isochrones per submission (6.6
through 10.12; 10.13 is not itself reachable by 0.02 steps from 6.6).
This is the form's own current default range at the fine spacing.

**Ages — linear grid.** Linear age from 0 to 4.0×10⁶ yr in steps of
10⁵ yr (0.1 Myr): 41 isochrones per submission, refining the youngest
ages below 10^6.6 yr = 3.9811 Myr; the handoff to the log grid is
rounded to 4.0 Myr, so the two grids overlap by at most that single
0.019 Myr interval and never leave a gap. Two fetch-time cautions are
inherent: the server's range arithmetic can drop a floating-point
endpoint (verified for log ages; if 4.0 Myr is dropped, coverage
remains gapless through the log grid's 3.9811 Myr start), and age
exactly 0 has not been exercised — if the server returns an empty
table for it, the first usable linear age is 10⁵ yr and the status
report will say so.

**Directory layout.** `parsec/<set-key>/<label>/` with
`label = [prefix]mh_<value>[_w<omega>]`: compositions render as the
existing directories do (`mh_p0.0`, `mh_m2.2`), boundary supplements
keep their precision (`mh_m2.19`, `mh_m1.4921`), v2.0 rotation gets a
suffix (`mh_p0.3_w0.40`), and v1.1/v1.0 keep their `v1.1_`/`v1.0_`
prefixes (their outputs carry no release echo, so the label carries
the identity). The two age grids of one cell live in this one
directory as `output.dat` (log) and `output_linear.dat` (linear), each
with its `.record.json`; one `MANIFEST.json` describes the cell.

## Fixed (non-varied) parameters

Every field outside the cell dimensions stays at the canonical
baseline — the request layer's verified default payload
(`cmd_form.DEFAULT_FIELDS`), with the per-set photometry required by
the bolometric-correction libraries. The payload of every archived
product records these values explicitly, so the record alone
reconstructs the full request:

| Field | Fixed value | Why it is not varied |
|---|---|---|
| `eta_reimers` | `0.2` | RGB mass-loss efficiency η in the Reimers (1975) law Ṁ = 4×10⁻¹³ η·L·R/M: sets how much envelope a star loses on the RGB, and with it the mass and core mass entering the TP-AGB (AGB brightness, lifetime, WD masses; `Mass`/`logg` shift from the RGB on). The form's default and the value of every archived table; upstream calls the regime η < 0.5 well-tested. Not applied at all for v2.0 (its tracks carry their own prescription). A η sweep (0.0–0.4, say) is a TP-AGB/RGB mass-loss systematic study, not a grid dimension. |
| `n_inTPC` | `10` | Numerical resolution of the COLIBRI TP-AGB integration — time steps per thermal-pulse cycle (Marigo et al. 2017). Higher values only sample the same tracks more finely (more rows per pulse cycle); no stellar physics changes. The form default; 20 doubles the resolution if a convergence check is ever wanted. |
| `imf_file` | `tab_imf/imf_kroupa_orig.dat` | Scales only the `int_IMF` column (number of stars up to each initial mass, per 1 M☉ born); isochrones are IMF-free. |
| `photsys_version` / `photsys_file` | `YBCnewVega` + `tab_mag_ubvrijhk` (YBC-served sets); `odfnew` + `tab_mag_lsst` (older sets) | Magnitude columns only. stellariso consumes physical columns; these are working placeholders the libraries actually serve (older sets have no YBC tables). |
| `extinction_av` | `0.0` | A foreground screen: shifts filter magnitudes by star-by-star Cardelli coefficients, leaves every physical column and `mbolmag` untouched (verified by paired submissions). Also not implemented upstream on rotating models. |
| `dust_sourceM` / `dust_sourceC` | `dpmod60alox40` / `AMCSIC15` | Circumstellar dust reddenings of mass-losing TP-AGB stars — magnitude columns only. |
| `kind_LPV` | `4` | Pulsation-period prescription (period0–4, pmode columns only). Option 4 (Trabucchi et al. 2021 non-linear FM) is the form's own checked default and the appropriate choice for fundamental-mode work. |
| `output_kind` | `0` | Isochrone tables — the only kind this library reads. |
| `output_gzip` | unchecked | Server force-gzips above 50 MB regardless; the reader detects gzip by content. |
| `track_postagb` | `no` | The only value the form declares. |
| `cmd_version`, hidden switches (`kind_interp`, `kind_postagb`, `kind_mag`, `kind_dust`, `output_evstage`), LF/population fields (`lf_*`, `sim_mtot`) | form defaults | Fixed wire constants; the LF/population fields are inert for isochrone tables. |

## Tiers and fetch order

Primary sets are fetched at full extent. Secondary sets are fetched
first at the sparse slice — anchor compositions [M/H] = −1.0, 0.0,
+0.3 plus both window edges (5 compositions per set, 30 cells, 60
submissions) — which pins each set's valid range and gives
metal-poor/solar/metal-rich comparison points against the primary
chains. Completing a secondary set later means fetching the remaining
designed cells; the design never changes.

## Measuring progress

`tools/parsec/blueprint_status.py DATABASE` compares a database against this
blueprint and writes the completion report (per set: parameter, range,
step, and counts; per cell: complete, log-only, pending, or re-fetch).
A cell is **complete** when both age grids are archived with conforming
payloads (grid values, canonical fixed fields, complete field set) and
the expected isochrone counts; **log-only** when the log half conforms
and the linear half is still to be fetched; **re-fetch** when the
archived table's age sampling does not match the design (kept in place,
never silently deleted or refetched — the marking is the review
artifact); **pending** when nothing is archived. Products that fall
outside the design entirely (historical option-variation tables) are
listed as superseded. The exit status is zero regardless: the report is
the deliverable, and deletions stay a human decision.
