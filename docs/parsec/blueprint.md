# The PARSEC form-product acquisition blueprint

This document declares the complete design of the form-computed half of a stellariso database: every product cell that will exist when the PARSEC build is finished, at which parameter values, and with which fixed settings. The machine-readable carrier is `stellariso.models.parsec.blueprint` (tests: `tests/parsec/test_blueprint.py`); the PARSEC family adapter (`stellariso.models.parsec.design`) turns it into the generic design vocabulary, `tools/db_status.py` measures any database against it, and `stellariso.build_database` acquires the cells through the same universal loop as every family (the management machinery is expanded in [../database.md](../database.md)). The wire protocol the submissions speak is documented in [cmd-form.md](cmd-form.md); this page fixes what is sent and why, not how.

## Coverage rule

Every form field falls into exactly one of three classes, and the class decides its treatment:

- **An axis** — a field that changes the computed isochrone table is a designed dimension of the cell space, carried at every value the form offers, wherever it is effective for that track set. "Changes the isochrone table" means any physical column, the TP-AGB extent, a phase label, the column set itself, or the table's own sampling moves when the field moves. The axes are: the track set, [M/H], initial rotation, the RGB Reimers mass-loss efficiency, the COLIBRI TP-cycle resolution (`n_inTPC`), the circumstellar dust mixture, and the LPV period prescription.
- **Fixed, offline-reproducible or output-shaping** — fields whose effect stellariso can reconstruct from archived columns without the server: the IMF (scales only `int_IMF`), foreground interstellar extinction (a star-by-star magnitude shift; verified by paired submissions — every physical column identical, filter magnitudes shifted, `mbolmag` unchanged), and the output switches (`output_kind` etc.). They stay at the canonical baseline below, recorded in full in every archived payload.

The classification line between axes and fixed fields is reproducibility, not column type: dust changes magnitudes only, yet it is an axis — the reddening is computed server-side from COLIBRI intermediate quantities the output does not carry, so no client can recompute it; extinction's shift, by contrast, is a documented Cardelli transform of archived magnitudes. Photometric systems would also be server-computed, but they change only which bolometric-correction table is joined; the design pins the working baseline per set (below) and leaves per-system photometry to on-demand submissions. `n_inTPC` is an axis of a different kind, admitted for coverage rather than physics: it resamples the same tracks (no physical quantity moves), but the archived table itself changes — different pulse-cycle phase points, only ~10% of table points shared between n=10 and n=20 — and the coverage rule reaches any change to the delivered table.

## The cell space

A **cell** is one point of the designed space: (track set, [M/H], ω_i, Reimers η, n_inTPC, dust mixture, LPV prescription). Each cell is one directory in the database holding two archived submissions: the log-age table `output.dat` and the linear-age refinement `output_linear.dat`, each with its own acquisition record. An axis that is inert for a set collapses to its canonical value (the request-layer baseline), so the archived products — which carry exactly those canonical values — are already canonical cells of this design.

Per-set axis applicability, with the evidence for each:

| Set | η (Reimers) | n_inTPC | Dust | LPV | Basis |
|---|---|---|---|---|---|
| `v1.2S_COLIBRI_web` | yes | yes | yes | yes | COLIBRI TP-AGB section; header echoes all the switches |
| `v2.0` | **no** | **no** | yes | yes | v2.0 headers carry the dust and LPV echo lines and period0–4/pmode columns, but no Reimers line (the form states eta is not applied for v2.0 tracks) and no "Thermal pulse cycles included" line (n_inTPC governs the COLIBRI section, which v2.0 does not use) |
| `v1.2S_COLIBRI_S35` / `S07` / `PR16` | yes | yes | yes | yes | COLIBRI TP-AGB section; Reimers and thermal-pulse echoes present |
| `v1.2S_no_colibri`, `v1.1`, `v1.0` | yes | **no** | **no** | **no** | Reimers echo present; the output is the reduced 17-column layout with no TP-AGB section and no period columns, so dust and LPV have nothing to act on (their header echo lines appear for every set — boilerplate) |

Full-design cell counts:

| Set (directory) | Tier | Tracks | [M/H] values | ω_i | η | n_inTPC | Dust | LPV | Cells |
|---|---|---|---|---|---|---|---|---|---|
| `v1.2S_COLIBRI_web` | primary | v1.2S + COLIBRI web chain (`S_LMC_08_web`) | 28 | 0 fixed | 6 | 3 | 20 | 4 | 40,320 |
| `v2.0` | primary | v2.0 (no COLIBRI option exists for it) | 27 | 11 | 1 (inert) | 1 (inert) | 20 | 4 | 23,760 |
| `v1.2S_COLIBRI_S35` | secondary | v1.2S + COLIBRI S_35 | 20 | 0 fixed | 6 | 3 | 20 | 4 | 28,800 |
| `v1.2S_COLIBRI_S07` | secondary | v1.2S + COLIBRI S_07 | 20 | 0 fixed | 6 | 3 | 20 | 4 | 28,800 |
| `v1.2S_COLIBRI_PR16` | secondary | v1.2S + COLIBRI PR16 (`NOV13`) | 28 | 0 fixed | 6 | 3 | 20 | 4 | 40,320 |
| `v1.2S_no_colibri` | secondary | v1.2S, no TP-AGB extension | 28 | 0 fixed | 6 | 1 | 1 | 1 | 168 |
| `v1.1` | secondary | v1.1 (no COLIBRI) | 28 | 0 fixed | 6 | 1 | 1 | 1 | 168 |
| `v1.0` | secondary | v1.0 (no COLIBRI) | 22 | 0 fixed | 6 | 1 | 1 | 1 | 132 |

Full design: **162,468 cells** and **324,936 submissions** (two age grids per cell). Which COLIBRI chain each option is: the web chain applies S_37 (Pastorelli 2020) for 0.008≤Z≤0.02, S_35 (Pastorelli 2019) for 0.0005≤Z≤0.006, and PR16 (Marigo 2013 + Rosenfield 2016) outside those ranges, which is what the output header echoes as "v1.2S + COLIBRI S_37 + S_35 + PR16"; PARSEC v2.0 is submitted with `track_colibri=no` — COLIBRI is a v1.2S-only option, and the v2.0 echo names only "PARSEC release v2.0" (Costa et al. 2019a,b code; Nguyen et al. 2022, 2025 tracks).

## The grids

What each axis option means scientifically (which dust mixture is which, which LPV prescription cites which paper) is expanded in [cmd-form.md](cmd-form.md); here each axis is declared as a design dimension with its evidence.

**Composition.** Steps of 0.1 dex across each set's full valid window, plus the exact window edges whenever they do not fall on the 0.1 dex grid. Window provenance: where the form states a [M/H] range for the set (v2.0: −2.19…+0.34; v1.2S and v1.1: −2.2…+0.5; v1.0: −1.5…+0.6), those stated numbers are the edges — they are the server's own acceptance range. The COLIBRI S_35/S_07 options are stated in Z only (0.0005≤Z≤0.03); their edges are converted through the form's own enrichment law (Y = 0.2485 + 1.78 Z, (Z/X)_☉ = 0.0207) to [M/H] −1.4921 and +0.3363. The PR16 option's Z range (0.0001–0.06) converts to [−2.1917, +0.6953], which does not narrow the stated v1.2S window — an upstream inconsistency resolved in favor of the stated window, which the server demonstrably serves across the full range. So: v2.0 carries 27 compositions (25 grid steps −2.1…+0.3 plus the edges −2.19 and +0.34), S_35/S_07 carry 20 (18 grid steps plus two converted edges), and the stated-window sets carry their on-grid edge-to-edge count (28, 28, 28, 28, 22).

**Initial rotation.** ω_i from 0 to 0.9 in steps of 0.1, plus 0.99 — 11 values. The form offers rotation for v2.0 only (0 ≤ ω_i ≤ 0.99, single text field `track_omegai`), the server interpolates isochrones between track rotation values (form news, 2024-10-01), and the header echo states the applied value ("Rotating tracks computed with omega_i=…"). ω = 0 reproduces the non-rotating v2.0 tables; every other set is fixed at ω = 0 and its payload records that.

**Reimers mass-loss efficiency (η).** 0.0 to 0.5 in steps of 0.1 — six values, covering the regime upstream calls well-tested ("mass loss works fine as long as eta < 0.5; check the results for higher values") including its stated boundary. η sets how much envelope a star loses on the RGB in the Reimers (1975) law Ṁ = 4×10⁻¹³ η·L·R/M, and with it the mass and core mass entering the TP-AGB (AGB brightness, lifetime, WD masses; `Mass`/`logg` shift from the RGB on). Archived web-chain tables at η = 0.0/0.2/0.4 (same [M/H], same age grid) differ in total rows 14,565/14,452/14,349 and TP-AGB rows 4,588/4,477/4,388 — the effect is real and monotone. Not applied at all for v2.0 (its tracks carry their own prescription); the axis collapses to the canonical 0.2 there.

**COLIBRI TP-cycle resolution (`n_inTPC`).** Designed {5, 10, 20} — the form default 10 plus its half and double, the resolutions whose variant tables are archived. It sets the time steps per thermal-pulse cycle in the COLIBRI integration (Marigo et al. 2017): no stellar physics changes, but the delivered table does — the sampling lands at different pulse-cycle phases, and archived n=5/10/20 tables share only ~10% of their points (TP-AGB row counts 2452/4477/8527), so any downstream use that treats the table as the TP-AGB record is affected. Applies to the four COLIBRI chains only: v2.0 and the no-TP-AGB sets have no COLIBRI section (their headers carry no "Thermal pulse cycles included" line). Extending the value set later is a documented design amendment, not a redesign.

**Circumstellar dust.** The O-rich source (`dust_sourceM`: `nodustM`, `sil`, `AlOx`, `dpmod60alox40`, `dpmod`) and the C-rich source (`dust_sourceC`: `nodustC`, `gra`, `AMC`, `AMCSIC15`) are independent axes of one isochrone — an AGB passes through both regimes — so the design crosses them: 5 × 4 = 20 combinations, including the dust-free pair that is the form's own default. The dust enters the TP-AGB magnitudes of mass-losing stars through the server's scaling relations (Marigo et al. 2008, Pastorelli et al. 2019) over COLIBRI quantities the output table does not carry; whether any physical column responds to the mixture — or magnitudes only — remains unattributed, but that the delivered table itself responds is verified by paired submissions (v2.0, 2026-10-17: sil/gra vs the canonical pair changes the data section). Applied where a TP-AGB section exists: the four COLIBRI chains and v2.0; the reduced 17-column sets have no section to redden.

**LPV period prescription (`kind_LPV`).** All four values: 1 (Trabucchi et al. 2017 preliminary FM/1OM relations), 2 (2019, linear pulsation models), 3 (2021, FM period and dominance from non-linear models), 4 (2021, periods and dominant regime from non-linear models — the form's checked default). Archived comparisons against option 4: option 2 changes `period0`–`period4` and `pmode`; option 3 changes `pmode` only; **option 1 changes the column set itself** (period2–4 are absent from its output). Designed wherever the output carries period columns: the four COLIBRI chains and v2.0.

**Ages — log grid.** log10(age/yr) from 6.6 to 10.13 in steps of 0.02 dex, identical for every set: 177 isochrones per submission (6.6 through 10.12; 10.13 is not itself reachable by 0.02 steps from 6.6). This is the form's own current default range at the fine spacing.

**Ages — linear grid.** Linear age from 10⁵ to 4.0×10⁶ yr in steps of 10⁵ yr (0.1 Myr): 40 isochrones per submission, refining the youngest ages below 10^6.6 yr = 3.9811 Myr; the handoff to the log grid is rounded to 4.0 Myr, so the two grids overlap by at most that single 0.019 Myr interval and never leave a gap — their age values never coincide (4.0 Myr is log10 6.602, not a 0.02-dex point), so both tables of a cell open together as one grid without duplicate points. Two server behaviors bound the grid (both probed live 2026-10-17): age exactly 0 is rejected — the server re-serves the input form with no output link and no error text — so 10⁵ yr is the first usable linear age; and the 4.0 Myr endpoint is retained exactly (linear range arithmetic does not drop it, unlike the log grid's floating-point endpoint drops).

## Directory layout and cell manifests

`parsec/<set-key>/<label>/` with `label = [prefix]mh_<value>[_w<omega>][_e<eta>][_n<n_inTPC>][_dM<dustM>][_dC<dustC>][_lpv<lpv>]`: compositions render as the archived directories do (`mh_p0.0`, `mh_m2.2`), boundary supplements keep their precision (`mh_m2.19`, `mh_m1.4921`), v2.0 rotation gets a suffix (`mh_p0.3_w0.40`), and v1.1/v1.0 keep their `v1.1_`/`v1.0_` prefixes (their outputs carry no release echo, so the label carries the identity). An axis at its canonical value renders no segment — every archived product directory (canonical on all new axes) is already a valid cell label; non-canonical values append their segments, e.g. `mh_p0.0_e0.0`, `mh_p0.0_n20`, `mh_m1.0_dMnodustM_dCnodustC_lpv2`, `mh_p0.0_e0.4_n5_lpv2`.

The two age grids of one cell live in this one directory as `output.dat` (log) and `output_linear.dat` (linear), each with its `.record.json`. One v2 `MANIFEST.json` describes the cell: the product identity (family, release, label, kind, citations), a `parts` map with the per-part archive facts (file, sha256, size, rows, retrieval time, record name) for both age grids, and a `family_section` pinning the cell's identity in this design — the axis values and the two designed age grids. Historical manifest shapes (a flat top-level sha256, or a `blueprint` section predating the v2 schema) stay readable through the manifest bridge, and `tools/db_transfer.py migrate-manifests` rewrites a whole database to clean v2.

## Fixed (non-varied) parameters

Every field outside the cell dimensions stays at the canonical baseline — the request layer's verified default payload (`cmd_form.DEFAULT_FIELDS`), with the per-set photometry required by the bolometric-correction libraries. The payload of every archived product records these values explicitly, so the record alone reconstructs the full request:

| Field | Fixed value | Why it is not varied |
|---|---|---|
| `imf_file` | `tab_imf/imf_kroupa_orig.dat` | Scales only the `int_IMF` column (number of stars up to each initial mass, per 1 M☉ born); isochrones are IMF-free, and the integral is recomputable client-side for any IMF. |
| `photsys_version` / `photsys_file` | `YBCnewVega` + `tab_mag_ubvrijhk` (YBC-served sets); `odfnew` + `tab_mag_lsst` (older sets) | Magnitude columns only, and only which bolometric-correction table is joined. Working placeholders the libraries actually serve (older sets have no YBC tables); per-system photometry stays an on-demand submission. |
| `extinction_av` | `0.0` | A foreground screen: shifts filter magnitudes by star-by-star Cardelli coefficients, leaves every physical column and `mbolmag` untouched (verified by paired submissions). Also not implemented upstream on rotating models. Recomputable client-side. |
| `output_kind` | `0` | Isochrone tables — the only kind this library reads. |
| `output_gzip` | unchecked | Server force-gzips above 50 MB regardless; the reader detects gzip by content. |
| `track_postagb` | `no` | The only value the form declares. |
| `cmd_version`, hidden switches (`kind_interp`, `kind_postagb`, `kind_mag`, `kind_dust`, `output_evstage`), LF/population fields (`lf_*`, `sim_mtot`) | form defaults | Fixed wire constants; the LF/population fields are inert for isochrone tables. |

## Fetch stages

Design and fetch order are separate. The full design fixes what the finished database contains; a fetch stage declares which designed cells are acquired now, as a pure subset — completing the rest later changes nothing about the layout. The current stage:

- **η**: 0.0, 0.2, 0.4 (three of the six designed values; canonical 0.2 where inert).
- **n_inTPC, dust and LPV**: canonical values only (10, `dpmod60alox40`/`AMCSIC15`, LPV 4).
- **[M/H] extent**: primary sets at full extent; secondary sets first at the sparse slice — anchor compositions [M/H] = −1.0, 0.0, +0.3 plus both window edges (5 compositions per set) — which pins each set's valid range and gives metal-poor/solar/metal-rich comparison points against the primary chains. Completing a secondary set later means `fetch_cells(set, sparse=False)`: the remaining designed compositions at the same axis values.

Stage totals: primary 381 cells (web 28×3, v2.0 297), secondary 90 (6 sets × 5×3) — **471 cells, 942 submissions**.

**Probes** — live checks run on small submissions before the stage's bulk (run 2026-10-17; each guards an assumption the design cannot verify offline): (1) age exactly 0 on the linear grid — rejected outright by the server, so the grid starts at 10⁵ yr; (2) the 4.0 Myr endpoint — retained exactly, no amendment; (3) ω > 0 with the YBC photometry — works: full 177-isochrone table, same column layout as ω = 0, every magnitude column populated, "Rotating tracks computed with omega_i=0.30" echoed; (4) v2.0 with a non-canonical dust pair and a non-canonical `kind_LPV` — both change the delivered table (a canonical re-submission was byte-identical to the archived table, validating the comparison), so both axes stay designed for v2.0.

## Building and measuring progress

`stellariso.build_database` acquires the form-channel half through the universal build loop: each fetch-stage cell submits its two age grids into one cell directory (the PARSEC adapter's `fetch_part` drives the request-layer client, verifying the server's header echo against the set's expected release string), archives both tables with their records, and writes one clean v2 cell MANIFEST. A part whose table is present and checksum-matches its recorded sha256 is never re-computed; a cell holding any nonconforming part — an archived table whose payload or isochrone count is not the designed one, or whose bytes no longer match the recorded checksum — is left untouched with a notice: no complementary part is fetched next to data the design disowns, and re-fetching it stays a human decision.

`python tools/db_status.py DATABASE` compares a database against this blueprint (through the family adapter) and writes the completion report for every family: per set the declarations (parameter, range, step, counts), per cell one line — `complete`, or `incomplete` with the per-part detail (`log ok; linear missing`, or the nonconforming reasons with a manual-review mark) — over the fetch-stage target, with beyond-target designed cells summarized and directories outside the design listed as superseded. A database root that still carries `blueprint_status.*` reports keeps them; `db_status.*` is the report that is regenerated. The exit status is zero regardless: the report is the deliverable, and deletions stay a human decision.
