# Unified parameters and field mappings

This document records the unified vocabulary every data source maps into, each source's own fields and physical parameters, and the mapping between the two layers. It is generated from the registry data files: `src/stellariso/registry/unified_parameters.json` holds stellariso's own definitions (unified fields, coarse stages, physical parameters), and each family's characteristics and mappings live in `src/stellariso/models/<family>/unified_parameters.json` next to its `catalog.json`. The library code loads and validates them as one registry — the backends read their field specs, phase mappings, and static parameter knowledge from it.

Regenerate the repository copy after editing the registry:

```bash
python tools/generator/generate_parameter_docs.py
```

## Unified evolutionary stages

The coarse stage vocabulary shared by all sources. Native phase codes map into these; unmapped codes resolve to `unknown` with a warning, never to a guess.

- `pre_main_sequence`
- `main_sequence`
- `subgiant`
- `red_giant_branch`
- `core_helium_burning`
- `early_asymptotic_giant_branch`
- `thermally_pulsing_asymptotic_giant_branch`
- `post_agb`
- `white_dwarf`
- `wolf_rayet`
- `unknown`

## Unified field vocabulary

| Unified field | Unit | Representation | Description |
|---|---|---|---|
| `initial_mass` | solMass | linear | initial (age-zero) mass of the star whose evolution the row samples |
| `current_mass` | solMass | linear | actual stellar mass at this point, including the mass-loss history |
| `log_luminosity` | dex(solLum) | log | log10 luminosity in solar units |
| `log_effective_temperature` | dex(K) | log | log10 effective temperature |
| `log_surface_gravity` | dex(cm / s2) | log | log10 surface gravity |
| `log_radius` | dex(solRad) | log | log10 radius in solar units |
| `phase` | — | linear | unified coarse evolutionary stage (see the stage vocabulary below); derived from the native phase code through a versioned mapping |
| `native_phase` | — | linear | the product's own evolutionary-stage code, preserved verbatim |
| `eep` | — | linear | equivalent evolutionary phase number (MIST EEP sampling) |
| `effective_temperature` | K | linear | effective temperature (10 ** log_effective_temperature) |
| `radius` | solRad | linear | stellar radius (10 ** log_radius) |
| `mass_loss_rate` | Msun/yr | linear | stellar mass-loss rate as a signed quantity; mapped only where the native convention is signed (MIST: negative while the star loses mass) |
| `log_mass_loss_rate` | — | log | log10 of the (positive) mass-loss rate in Msun/yr; kept in native representation where the source prints a positive log quantity (PARSEC logMdot) |
| `he_core_mass` | solMass | linear | helium-core mass |
| `he_core_mass_tp` | solMass | linear | H-exhausted core mass on the TP-AGB (0 before the TP-AGB) |
| `imf_integral` | — | linear | integral of the selected IMF (number of stars, normalised to 1 Msun of initially formed stars) from 0 up to the current initial mass |
| `c_over_o` | — | linear | photospheric C/O ratio |
| `co_core_mass` | solMass | linear | carbon-oxygen (He-exhausted) core mass |

## Physical parameter vocabulary

Physical parameters a model product can carry. The role a parameter plays in a specific source (axis, fixed, derived, implicit, not applicable) is listed per source below; the value notions — available grid values, fixed values, selection pins — stay separate in the API.

| Parameter | Unit | Convention | Description |
|---|---|---|---|
| `log_age` | dex(log10(age/yr)) | — | log10 of the isochrone age in years |
| `initial_mass` | solMass | — | initial (age-zero) stellar mass; the axis an isochrone product varies within one composition |
| `initial_feh` | dex | [Fe/H] of the initial composition | initial metallicity as [Fe/H] |
| `initial_z` | — | mass fraction | initial metal mass fraction Z |
| `initial_helium` | — | mass fraction | initial helium mass fraction Y |
| `alpha_fe` | dex | [a/Fe] | alpha enhancement of the initial composition |
| `initial_rotation` | — | v_initial / v_critical (surface equatorial) | initial rotation ratio |
| `eta_reimers` | — | Reimers efficiency | RGB Reimers mass-loss efficiency |
| `mixing_length` | — | alpha_ML | mixing-length parameter |
| `overshoot` | — | — | convective overshoot setting |
| `atomic_diffusion` | — | — | atomic-diffusion setting |

## MIST (`mist`)

Field mapping version: `1`.

- Column meanings follow the official MIST table README (README_tables.pdf): the phase column is the FSPS phase type, and the same document defines the primary EEPs used as anchors.
- MIST's RGB code (2) covers the subgiant branch and the RGB together; it maps to red_giant_branch rather than splitting it.
- Phase 6 (postAGB) spans post-AGB through the white-dwarf cooling sequence; it maps to post_agb and must not be read as an enumerated WD population.
- Mass-loss sign convention: star_mdot is negative while the star is losing mass. The unified mass_loss_rate is mapped only for MIST because of this signed convention.
- current_mass context: MIST v1.2 uses Reimers-type RGB winds with efficiency anchored near eta ~ 0.1 and Blocker-type AGB winds.

### Isochrone tables (`isochrones`)

#### Field mappings

| Unified field | Native source | Origin | Transformation | Notes |
|---|---|---|---|---|
| `eep` | `EEP` | native | — | — |
| `initial_mass` | `initial_mass` | native | — | mass at age zero of the model whose isochrone point this row interpolates |
| `current_mass` | `star_mass` | native | — | actual (wind-reduced) mass at this point; MIST v1.2 uses Reimers-type RGB winds with efficiency anchored near eta ~ 0.1 and Blocker-type AGB winds |
| `log_effective_temperature` | `log_Teff` | native | — | — |
| `effective_temperature` | `log_Teff` | transformed_native | 10 ** x | — |
| `log_luminosity` | `log_L` | native | — | — |
| `log_surface_gravity` | `log_g` | native | — | — |
| `log_radius` | `log_R` | native | — | — |
| `radius` | `log_R` | transformed_native | 10 ** x | — |
| `native_phase` | `phase` | native | — | FSPS phase code as printed by MIST |
| `phase` | `phase` | derived | MIST FSPS phase code mapped to unified coarse stages; codes 1, 7, 8 are not used by MIST | — |
| `mass_loss_rate` | `star_mdot` | native | — | stellar mass-loss rate; negative means the star is losing mass (MIST sign convention) |
| `he_core_mass` | `he_core_mass` | native | — | — |

#### Phase mapping

| Native code | Meaning | Unified stage |
|---|---|---|
| -1 | pre-main sequence (FSPS phase type) | `pre_main_sequence` |
| 0 | main sequence | `main_sequence` |
| 2 | subgiant + red giant branch | `red_giant_branch` |
| 3 | core helium burning | `core_helium_burning` |
| 4 | early AGB | `early_asymptotic_giant_branch` |
| 5 | thermally pulsing AGB | `thermally_pulsing_asymptotic_giant_branch` |
| 6 | post-AGB through WD cooling | `post_agb` |
| 9 | Wolf-Rayet (documented MS/WR overlap caution for very massive stars) | `wolf_rayet` |

#### Primary EEP anchors

| Anchor | EEP number |
|---|---|
| PMS | 1 |
| ZAMS | 202 |
| IAMS | 353 |
| TAMS | 454 |
| RGB_TIP | 605 |
| ZACHeB | 631 |
| TACHeB | 707 |
| TPAGB_START | 808 |
| POST_AGB | 1409 |
| WDCS | 1710 |

#### Physical parameters

| Parameter | Role | Value / source | Notes |
|---|---|---|---|
| `log_age` | axis (varies across the published grid) | file values `log_age` | — |
| `initial_feh` | axis (varies across the published grid) | file values `initial_feh` | initial metallicity as [Fe/H]; the published v1.2 tarball suite uses a fixed set, form-generated files can be effectively continuous |
| `alpha_fe` | axis (varies across the published grid) | file values `alpha_fe` | — |
| `initial_rotation` | axis (varies across the published grid) | `0.0, 0.4` | rotation values published for the MIST v1.2 isochrone suite (separate tarballs per v/vcrit); the header of each file states which one it holds |
| `initial_helium` | fixed (known value for the whole product) | file value `initial_helium` | initial helium mass fraction (MIST Y-Z grid point) |
| `initial_z` | fixed (known value for the whole product) | file value `initial_z` | initial metal mass fraction (MIST Y-Z grid point) |
| `mixing_length` | implicit (used by the model, not recoverable) | — | MESA calibrates alpha_ML on the Sun; value not in data |
| `overshoot` | implicit (used by the model, not recoverable) | — | not_reported |
| `atomic_diffusion` | implicit (used by the model, not recoverable) | — | not_reported |

### Scientific references

- Choi, J., Dotter, A., Conroy, C., et al. 2016, ApJ, 823, 102 (bibcode `2016ApJ...823..102C`)
- Dotter, A. 2016, ApJS, 222, 8 (bibcode `2016ApJS..222....8D`)
- Paxton, B., et al. 2011, ApJS, 192, 3 (MESA I) (bibcode `2011ApJS..192....3P`)

## padova (`padova`)

Field mapping version: `1`.

- Sources are the two static CDS/VizieR catalogs, not the model team's site: padova/2000 = J/A+AS/141/371 (Girardi et al. 2000), padova/1994 = J/A+AS/106/275 (Bertelli et al. 1994); the original host pleiadi.pd.astro.it is effectively dead. Both catalogs publish no checksums; sha256 is computed at download and recorded.
- Neither archive carries per-row evolutionary-stage columns. padova/2000 phases are anchored on the source's own isochsum.dat characteristic points (its G1 stage labels: TO, RGBb, RGBt, BHeb, EHeb, 1TP, AGBt, Cb); padova/1994 phases are derived by stellariso's own shape rules over the isochrone's own columns — declared here, empirically locked on the full archive (the source documents no stage vocabulary at all). Both mappings are declared derived and versioned by mapping_version.
- The files state neither composition nor release in their content: padova/1994 tables carry no header and no Z column, so each table's (Z, Y) comes from the catalog ReadMe's documented file list and the canonical file names table1..table6 are required; padova/2000 carries its Z and Overshoot as columns but its Y-per-Z pairing and the solar identification (Z=0.019) come from the ReadMe text.
- [Fe/H] is a stellariso-declared conversion under the scaled-solar assumption: [Fe/H] = log10(Z/Z_ref) with each release's own solar Z (padova/2000: Z_ref = 0.019, ReadMe-declared solar composition; padova/1994: Z_ref = 0.02, the solar point of the paper's composition grid). The two references differ and are never shared across releases.
- padova/2000 isochrones start at the ZAMS and end at the thermally pulsing AGB or carbon ignition (no post-AGB/WD rows); padova/1994 isochrones extend beyond the AGB tip to the white-dwarf stage after the planetary-nebula phase (paper abstract).
- padova/2000 Mact can exceed Mini by up to ~5e-5 Msun on 1,177 of 64,381 rows — a print-precision artifact of Mact's F6.4 format against Mini's F10.8, not a physics violation; assertions must use the file's precision.
- padova/1994 current mass M is non-monotonic within an isochrone by construction (ReadMe Note 1: it drops at the RGB-to-ZAHB and AGB-to-post-AGB transitions under the mass-loss prescription); initial_mass is recovered by inverting the tabulated FLUM and is non-decreasing in every published block.
- padova/1994 star mass is M where Mwind = 0 and Mwind where Mwind > 0 (ReadMe Note 2: for massive stars the actual mass is the wind-reduced value; Mwind is printed only in the youngest isochrones).
- The Reimers eta of both releases' RGB mass loss is stated in the papers, not in the catalog ReadMes; until extracted from the paper texts it is recorded implicit/not_reported rather than assumed.

### isochrones_2000 (`isochrones_2000`)

#### Field mappings

| Unified field | Native source | Origin | Transformation | Notes |
|---|---|---|---|---|
| `initial_mass` | `Mini` | native | — | initial mass of the star whose evolution the row samples (Mini column) |
| `current_mass` | `Mact` | native | — | actual mass including the mass-loss history (Mact column); can exceed Mini by up to ~5e-5 Msun through F6.4 print rounding |
| `log_luminosity` | `logL` | native | — | — |
| `log_effective_temperature` | `logTeff` | native | — | — |
| `effective_temperature` | `logTeff` | transformed_native | 10 ** x | — |
| `log_surface_gravity` | `logg` | native | — | — |
| `phase` | `isochsum.dat Stage anchors` | derived | stage boundaries at the isochsum.dat characteristic-point initial masses of this isochrone (G1 labels): rows below M_TO are main_sequence; subgiant starts at M_TO; red_giant_branch at M_RGBb (or Brg); core_helium_burning at M_RGBt (or Tip, or BHeb); early_asymptotic_giant_branch at M_EHeb; thermally_pulsing_asymptotic_giant_branch at M_1TP. Interior markers (Te-m, Te-M, L-M, L-m) are not boundaries; a missing anchor extends the previous stage; rows beyond the last anchor keep it (massive isochrones end at C-ignition, Cb, and stay in the last AGB stage — the unified vocabulary has no carbon-ignition stage). Requires the isochsum.dat companion next to isochron.dat | — |
| `native_phase` | — | missing | — | no per-row phase column exists; the source's own stage labels appear only at isochsum.dat characteristic points and anchor the derived phase |
| `log_radius` | — | missing | — | no radius column is published; log_surface_gravity carries the size information the unified vocabulary needs |
| `eep` | — | missing | — | isochrones are tabulated in initial mass, not EEPs |

#### Phase mapping

| Native code | Meaning | Unified stage |
|---|---|---|

#### Physical parameters

| Parameter | Role | Value / source | Notes |
|---|---|---|---|
| `log_age` | axis (varies across the published grid) | file values `log_age` | log10(age/yr) as printed per row (F5.2); 7.80 to 10.25, step 0.05, in every (Overshoot, Z) column of the grid |
| `initial_z` | axis (varies across the published grid) | file values `initial_z` | exact metallicity value of the isochrone (Z column); six published values 0.0004 to 0.03 |
| `initial_helium` | axis (varies across the published grid) | file values `initial_helium` | one Y per published Z, from the ReadMe description ([0.0004,0.23], [0.001,0.23], [0.004,0.24], [0.008,0.25], [0.019,0.273] solar, [0.03,0.30]); not tabulated in the data file |
| `overshoot` | axis (varies across the published grid) | file values `overshoot` | the Overshoot column: 1 = models with a moderate amount of convective overshoot (the whole grid), 0 = solar-comparison set computed with the classical Schwarzschild criterion (solar Z only) |
| `initial_feh` | derived (stated relation) | file values `initial_feh`; relation `log10(initial_z / Z_ref)` (Z_ref=0.019) | scaled-solar conversion anchored on the ReadMe's declared solar composition [Z=0.019, Y=0.273]; a recorded parameter — the selection coordinate is the native initial_z |
| `alpha_fe` | fixed (known value for the whole product) | `0.0` | the published composition sets are scaled-solar [Z, Y] pairs; the alpha-enhanced grids of the same generation are a separate publication (Salasnich et al. 2000) |
| `initial_rotation` | not applicable under this physics | — | the models are non-rotating; no rotation axis exists in this release |
| `eta_reimers` | implicit (used by the model, not recoverable) | — | RGB mass loss with a Reimers-type law is in the models (Mact carries its history); the efficiency value is stated in the paper text, not in the catalog — record pending paper extraction |
| `mixing_length` | implicit (used by the model, not recoverable) | — | not_reported |

### isochrones_1994 (`isochrones_1994`)

#### Field mappings

| Unified field | Native source | Origin | Transformation | Notes |
|---|---|---|---|---|
| `initial_mass` | `FLUM` | derived | inversion of the tabulated Salpeter luminosity-function integral: FLUM = Mini^(1-alpha)/(1-alpha) with alpha = 2.35 and A = 1 (ReadMe note), so Mini = ((alpha-1) * \|FLUM\|)^(1/(1-alpha)); verified non-decreasing in every published block (the current-mass column is NOT, by construction) | — |
| `current_mass` | `M, Mwind` | derived | M where Mwind = 0, Mwind where Mwind > 0 (ReadMe Note 2: for massive stars the actual mass is the wind-reduced value; Mwind is tabulated only in the youngest isochrones) | — |
| `log_luminosity` | `Mbol` | derived | logL = (Mbol_sun - Mbol) / 2.5 with Mbol_sun = 4.77, the zero point of the same group's immediately following release (derivable exactly from Girardi et al. 2000's own paired logL and Mbol columns, spread 1e-3 = print rounding); the 1994 paper's stated constant has not been re-verified from the paper text | — |
| `log_effective_temperature` | `log(Teff)` | native | — | — |
| `effective_temperature` | `log(Teff)` | transformed_native | 10 ** x | — |
| `log_surface_gravity` | `M (or Mwind), Mbol, log(Teff)` | derived | surface-gravity closure from the tabulated quantities: logg = log10(M/Msun) + 4 log10(Teff/Teff_sun) - log10(L/Lsun) + log10(g_sun) with g_sun = 10^4.438 cm/s2, Teff_sun = 5777 K, and L through the declared Mbol_sun = 4.77 chain; the constants are declared by this mapping, not stated by the source | — |
| `phase` | `shape rules over log(Teff), Mbol, M, FLUM` | derived | stellariso-derived shape rules per isochrone, declared here (the archive publishes no stage vocabulary and documents no classification): main_sequence up to the turnoff, the first log(Teff) maximum followed by a >= 0.1 dex fall (the descent toward the giants; the global maximum would misfire on the youngest isochrones whose stripped Wolf-Rayet tail is hotter than any main-sequence star); red_giant_branch (subgiant not separated, the MIST phase-2 precedent) up to the first logL local maximum followed by a >= 0.15 dex decrease (the RGB tip; the RGB-to-HB mass drop that follows completes it); core_helium_burning until logL re-exceeds that tip luminosity; early_asymptotic_giant_branch until the second current-mass drop (AGB-to-post-AGB, told from the RGB drop by the post-drop luminosity staying within 0.3 dex of the tip); post_agb up to the tail's maximum log(Teff); white_dwarf after it; and wolf_rayet for post-turnoff rows hotter than the turnoff with initial mass above 10 Msun (stripped massive cores — the unified vocabulary's stage for them; nothing else in these isochrones can be both). A block whose chain does not resolve consistently is classified 'unknown' with a warning, never guessed | — |
| `native_phase` | — | missing | — | the archive publishes no stage vocabulary at all; the derived phase is pure shape analysis of the source's own columns |
| `log_radius` | — | missing | — | no radius column is published; log_surface_gravity carries the size information the unified vocabulary needs |
| `eep` | — | missing | — | isochrones are tabulated in luminosity-function order, not EEPs |

#### Phase mapping

| Native code | Meaning | Unified stage |
|---|---|---|

#### Physical parameters

| Parameter | Role | Value / source | Notes |
|---|---|---|---|
| `log_age` | axis (varies across the published grid) | file values `log_age` | log10(age/yr) as printed per row (F6.3); 6.60 to 10.30 across the six tables (one table carries 6.60 to 10.24) |
| `initial_z` | axis (varies across the published grid) | file values `initial_z` | per-table Z from the catalog ReadMe's file list (the data files state no composition): table1 0.0004, table2 0.001, table3 0.004, table4 0.008, table5 0.02, table6 0.05 — the canonical file names are therefore required |
| `initial_helium` | axis (varies across the published grid) | file values `initial_helium` | per-table Y from the same ReadMe list: 0.23, 0.23, 0.24, 0.25, 0.28, 0.352; the table2 set is computed with Huebner et al. (1977) opacities, the rest with Iglesias et al. (1992) |
| `initial_feh` | derived (stated relation) | file values `initial_feh`; relation `log10(initial_z / Z_ref)` (Z_ref=0.02) | scaled-solar conversion anchored on the paper grid's solar composition [Z=0.02, Y=0.28] (the Padova-1994 generation's solar point); differs from padova/2000's 0.019 — each release declares its own; a recorded parameter — the selection coordinate is the native initial_z |
| `alpha_fe` | fixed (known value for the whole product) | `0.0` | the published composition sets are scaled-solar [Z, Y] pairs |
| `initial_rotation` | not applicable under this physics | — | the models are non-rotating; no rotation axis exists in this release |
| `overshoot` | implicit (used by the model, not recoverable) | — | the convective-overshoot setting of the 1994 isochrone models is described in the paper text, not in the catalog ReadMe |
| `eta_reimers` | implicit (used by the model, not recoverable) | — | mass loss enters the tabulated current mass (ReadMe Note 1 describes the RGB and TP-AGB prescriptions by paper section); the efficiency values are stated in the paper text, not in the catalog — record pending paper extraction |
| `mixing_length` | implicit (used by the model, not recoverable) | — | not_reported |

### Scientific references

- Girardi, L., Bressan, A., Bertelli, G., Chiosi, C. 2000, A&AS, 141, 371 (bibcode `2000A&AS..141..371G`)
- Bertelli, G., Bressan, A., Chiosi, C., Fagotto, F., Nasi, E. 1994, A&AS, 106, 275 (bibcode `1994A%26AS..106..275B`)

## PARSEC / Padova (`parsec`)

Field mapping version: `1`.

- Column names follow the CMD isochrone-table format (see the reader module).
- Stage labels follow the official CMD FAQ, which itself cautions that labels are approximate and not carefully checked for all masses and metallicities.
- Mass-loss sign convention difference: MIST's star_mdot is negative while the star loses mass; CMD's logMdot is log10 of the (positive) rate. Both are preserved natively; the unified signed mass_loss_rate is mapped only for MIST, and PARSEC keeps logMdot under log_mass_loss_rate to avoid a silent sign/representation change.

### CMD isochrone tables (documented layout) (`cmd_table`)

#### Field mappings

| Unified field | Native source | Origin | Transformation | Notes |
|---|---|---|---|---|
| `initial_mass` | `M_ini` | native | — | initial (age-zero) mass of the isochrone point |
| `current_mass` | `M_act` | native | — | actual mass including the mass-loss history (Reimers RGB winds with the eta stated in the file header) |
| `log_luminosity` | `logL/Lo` | native | — | — |
| `log_effective_temperature` | `logTe` | native | — | — |
| `log_surface_gravity` | `logG` | native | — | — |
| `native_phase` | `label` | native | — | CMD evolutionary stage label (approximate per the official FAQ) |
| `phase` | `label` | derived | CMD stage label mapped to unified coarse stages | — |
| `imf_integral` | `int_IMF` | native | — | — |
| `c_over_o` | `C/O` | native | — | photospheric C/O ratio (ZAMS value printed before the TP-AGB) |
| `he_core_mass_tp` | `M_hec` | native | — | H-exhausted core mass on the TP-AGB (0 before it) |
| `log_mass_loss_rate` | `logMdot` | native | — | log10 of the mass-loss rate in Msun/yr (positive quantity; meaningful mainly on the TP-AGB) |

#### Phase mapping

| Native code | Meaning | Unified stage |
|---|---|---|
| 0 | pre-main sequence | `pre_main_sequence` |
| 1 | main sequence | `main_sequence` |
| 2 | subgiant branch | `subgiant` |
| 3 | red giant branch | `red_giant_branch` |
| 4 | core He burning, stage I | `core_helium_burning` |
| 5 | core He burning, stage II | `core_helium_burning` |
| 6 | core He burning, stage III | `core_helium_burning` |
| 7 | early AGB | `early_asymptotic_giant_branch` |
| 8 | thermally pulsing AGB | `thermally_pulsing_asymptotic_giant_branch` |
| 9 | post-AGB | `post_agb` |

#### Physical parameters

| Parameter | Role | Value / source | Notes |
|---|---|---|---|
| `log_age` | axis (varies across the published grid) | file values `log_age` | — |
| `initial_z` | — | file values `initial_z`; only when {'available': 'initial_z'} or — | — |
| `initial_helium` | derived (stated relation) | relation `Y_p + dYdZ * initial_z` (Y_p=0.2485, dYdZ=1.78) | scaled-solar helium enrichment law of the PARSEC v1.2S grid (stated on the CMD form) |
| `alpha_fe` | fixed (known value for the whole product) | `0.0` | scaled-solar (CAF09) composition; the CMD v1.2S products carry no alpha enhancement |
| `initial_rotation` | not applicable under this physics | — | PARSEC v1.2S tracks are non-rotating; rotation exists only in the PARSEC v2.0 products |
| `eta_reimers` | fixed (known value for the whole product) | file value `eta_reimers`; only when {'available': 'eta_reimers'} | RGB Reimers mass-loss efficiency (file header) |
| `mixing_length` | implicit (used by the model, not recoverable) | — | not_reported |

### CMD 3.9 web-form isochrone tables (`cmd_table_3_9`)

- Real CMD 3.9 output layout (verified against server-computed tables, 2026-10-14): per-row columns Zini MH logAge Mini int_IMF Mass logL logTe logg label McoreTP C_O period0..period4 pmode Mloss tau1m X Y Xc Xn Xo Cexcess Z plus the photometric-system magnitudes; every isochrone block is introduced by a REPEATED column-name comment line (no per-block Z=/Y=/X= headers exist) and the file ends with '#isochrone terminated'.
- X and Y are the CURRENT surface H and He mass fractions; Y drifts along the isochrone (dredge-up, AGB) and equals the initial helium at the ZAMS, confirming the enrichment law used for the derived initial_helium parameter.
- Zini and MH state the initial metallicity and [M/H] of the isochrone (constant within a block; MH = 0 returns Z = 0.014711, not the present-solar 0.01524).
- No unified mapping exists for log_mass_loss_rate in this layout: the real 3.9 vocabulary has no logMdot column. Mloss is the integrated mass lost (not a rate) and tau1m is left unmapped as well; both stay available under their native names.
- period0..period4, pmode, Xc, Xn, Xo, Cexcess, and the actual surface Z are preserved natively without unified mappings.

#### Field mappings

| Unified field | Native source | Origin | Transformation | Notes |
|---|---|---|---|---|
| `initial_mass` | `Mini` | native | — | initial (age-zero) mass of the isochrone point |
| `current_mass` | `Mass` | native | — | actual mass including the mass-loss history (Reimers RGB winds with the eta stated in the file header) |
| `log_luminosity` | `logL` | native | — | — |
| `log_effective_temperature` | `logTe` | native | — | — |
| `log_surface_gravity` | `logg` | native | — | — |
| `native_phase` | `label` | native | — | CMD evolutionary stage label (approximate per the official FAQ) |
| `phase` | `label` | derived | CMD stage label mapped to unified coarse stages | — |
| `imf_integral` | `int_IMF` | native | — | — |
| `c_over_o` | `C_O` | native | — | photospheric C/O ratio (ZAMS value printed before the TP-AGB) |
| `he_core_mass_tp` | `McoreTP` | native | — | H-exhausted core mass on the TP-AGB (0 before it) |

#### Phase mapping

| Native code | Meaning | Unified stage |
|---|---|---|
| 0 | pre-main sequence | `pre_main_sequence` |
| 1 | main sequence | `main_sequence` |
| 2 | subgiant branch | `subgiant` |
| 3 | red giant branch | `red_giant_branch` |
| 4 | core He burning, stage I | `core_helium_burning` |
| 5 | core He burning, stage II | `core_helium_burning` |
| 6 | core He burning, stage III | `core_helium_burning` |
| 7 | early AGB | `early_asymptotic_giant_branch` |
| 8 | thermally pulsing AGB | `thermally_pulsing_asymptotic_giant_branch` |
| 9 | post-AGB | `post_agb` |

#### Physical parameters

| Parameter | Role | Value / source | Notes |
|---|---|---|---|
| `log_age` | axis (varies across the published grid) | file values `log_age` | — |
| `initial_z` | axis (varies across the published grid) | file values `initial_z` | initial metal mass fraction, stated per row by the Zini column |
| `initial_helium` | derived (stated relation) | relation `Y_p + dYdZ * initial_z` (Y_p=0.2485, dYdZ=1.78) | scaled-solar helium enrichment law of the PARSEC v1.2S grid (stated on the CMD form); the table's own Y column equals it at the ZAMS |
| `alpha_fe` | fixed (known value for the whole product) | `0.0` | scaled-solar (CAF09) composition; the CMD v1.2S products carry no alpha enhancement |
| `initial_rotation` | not applicable under this physics | — | PARSEC v1.2S isochrones are non-rotating; rotation exists only in the PARSEC v2.0 products |
| `eta_reimers` | fixed (known value for the whole product) | file value `eta_reimers`; only when {'available': 'eta_reimers'} | RGB Reimers mass-loss efficiency (file header) |
| `mixing_length` | implicit (used by the model, not recoverable) | — | not_reported |

### Scientific references

- Bressan, A., Marigo, P., Girardi, L., et al. 2012, MNRAS, 427, 127 (bibcode `2012MNRAS.427..127B`)
- Marigo, P., Bressan, A., Nanni, A., Girardi, L., Pumo, M. L. 2013, MNRAS, 434, 488 (bibcode `2013MNRAS.434..488M`)
- Marigo, P., Girardi, L., Bressan, A., et al. 2017, ApJ, 835, 77 (bibcode `2017ApJ...835...77M`)
- Chen, Y., Girardi, L., Bressan, A., et al. 2014, MNRAS, 444, 2525 and 2015, MNRAS, 452, 1068
- Pastorelli, G., et al. 2019, MNRAS, 485, 5666 and 2020, MNRAS
