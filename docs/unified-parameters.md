# Unified parameters and field mappings

This document records the unified vocabulary every data source maps into, each source's own fields and physical parameters, and the mapping between the two layers. It is generated from the registry data files: `src/stellariso/registry/unified_parameters.json` holds stellariso's own definitions (unified fields, coarse stages, physical parameters), and each family's characteristics and mappings live in `src/stellariso/models/<family>/unified_parameters.json` next to its `catalog.json`. The library code loads and validates them as one registry — the backends read their field specs, phase mappings, and static parameter knowledge from it.

Regenerate the repository copy after editing the registry:

```bash
python tools/generate_parameter_docs.py
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
| `initial_mass` | solMass | — | initial (age-zero) stellar mass; the axis a track grid varies within one composition |
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

## PARSEC / Padova (`parsec`)

Field mapping version: `1`.

- Column names follow the CMD isochrone-table format (see the reader module).
- Stage labels follow the official CMD FAQ, which itself cautions that labels are approximate and not carefully checked for all masses and metallicities.
- Mass-loss sign convention difference: MIST's star_mdot is negative while the star loses mass; CMD's logMdot is log10 of the (positive) rate. Both are preserved natively; the unified signed mass_loss_rate is mapped only for MIST, and PARSEC keeps logMdot under log_mass_loss_rate to avoid a silent sign/representation change.

### CMD isochrone tables (hand-downloaded) (`cmd_table`)

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

### v1.2S stellar tracks (official archive) (`tracks_v12s`)

- Files follow the official readme of the PARSEC v1.2S track database (Bressan+2012; Chen+2014; Tang+2014; Chen+2015; Fu+2018).
- One plain-text file per initial mass, whitespace-separated: MODELL MASS AGE LOG_L LOG_TE LOG_R LOG_RAT M_CORE_HE M_CORE_C H_CEN HE_CEN C_cen O_cen LX LY LC LNEUTR L_GRAV H_SUP HE_SUP C_SUP N_SUP O_SUP PHASE. AGE is in years; LOG_R is log10(R/cm).
- The single *ADD.DAT file in each zip is discarded (official readme instruction: it only exists to merge sections across critical points).
- The *.HB.DAT files are horizontal-branch (post-helium-flash) tracks of low-mass stars; their PHASE numbering restarts with its own meaning and uses the separate hb mapping. They are parsed but excluded from isochrone synthesis (the helium flash is discontinuous; bridging it is not attempted).
- The PHASE column is fractional between integers by design; codes are floored before stage mapping.
- LOG_RAT (log mass-loss rate) keeps its -30 'no mass loss' sentinel and is therefore not exposed as a unified field.
- The phase-code mapping is stellariso's derivation from physical inspection of the published tracks, not an official enumeration — the official readme names PHASE but lists no code table.

#### Field mappings

| Unified field | Native source | Origin | Transformation | Notes |
|---|---|---|---|---|
| `initial_mass` | `initial_mass` | file_metadata | — | initial mass, stated by the track filename (Z...Y...OUTA..._M<mass:7.3f>.DAT pattern), not by a column |
| `current_mass` | `MASS` | native | — | stellar mass in Msun (official readme: 'stellar mass'); constant along tracks without wind mass loss |
| `log_luminosity` | `LOG_L` | native | — | — |
| `log_effective_temperature` | `LOG_TE` | native | — | log10 effective temperature in K (official readme words it as 'effective temperature in K'; the printed values are the base-10 logarithm) |
| `log_radius` | `LOG_R` | transformed_native | x - log10(Rsun/cm) | official readme: 'stellar radius in Log cm'; shifted to log10(R/Rsun) with the IAU 2015 nominal solar radius |
| `log_surface_gravity` | `MASS, LOG_R` | derived | log10(G * MASS[Msun] * Msun_g / (10**LOG_R[cm])**2), G = 6.67430e-8 cm3 g-1 s-2 (CODATA 2018), Msun_g = 1.98847e33 g (IAU 2015 nominal solar mass); the tracks print no gravity column | — |
| `he_core_mass` | `M_CORE_HE` | native | — | official readme: 'mass of H exhausted core' — the core inside the H-burning shell |
| `co_core_mass` | `M_CORE_C` | native | — | official readme: 'mass of He exhausted core' |
| `native_phase` | `PHASE` | native | — | PARSEC track phase (critical point number); fractional values between integers are intentional, designed for interpolation |
| `phase` | `PHASE` | derived | floor(PHASE + 1e-9) mapped to unified coarse stages; the official readme names the column but does not enumerate the codes — the mapping below was derived from the physical state at each integer transition (central abundances, nuclear luminosity fractions, core masses) in the published Z=0.0001Y0.249 set | — |
| `log_mass_loss_rate` | — | missing | — | not mapped: the track LOG_RAT column uses a -30 sentinel for 'no mass loss', which is not a log10 rate |

#### Phase mapping

| Native code | Meaning | Unified stage |
|---|---|---|
| 1 | track start, fully convective pre-main sequence (LX = 0) | `pre_main_sequence` |
| 2 | pre-main sequence, nuclear burning beginning (LX << 1) | `pre_main_sequence` |
| 3 | late pre-main sequence (LX rising) | `pre_main_sequence` |
| 4 | approaching the ZAMS (LX ~ 1) | `pre_main_sequence` |
| 5 | ZAMS (LX = 1) | `main_sequence` |
| 6 | end of the main sequence (H_CEN ~ 0.03) | `main_sequence` |
| 7 | central hydrogen exhausted (H_CEN = 0) | `subgiant` |
| 8 | shell hydrogen burning / Hertzsprung crossing into the giant branch | `red_giant_branch` |
| 9 | ascending the giant branch | `red_giant_branch` |
| 10 | upper giant branch | `red_giant_branch` |
| 11 | core helium ignition | `core_helium_burning` |
| 12 | core helium burning settling | `core_helium_burning` |
| 13 | core helium burning (HE_CEN decreasing) | `core_helium_burning` |
| 14 | central helium exhausted (HE_CEN = 0), early AGB | `early_asymptotic_giant_branch` |

#### Phase mapping — HB track files

| Native code | Meaning | Unified stage |
|---|---|---|
| 1 | horizontal-branch track start, core helium burning (H_CEN = 0, HE_CEN ~ 0.95) | `core_helium_burning` |
| 2 | core helium burning (HE_CEN ~ 0.5) | `core_helium_burning` |
| 3 | late core helium burning (HE_CEN ~ 0.3) | `core_helium_burning` |
| 4 | central helium exhausted (HE_CEN = 0), AGB ascent | `early_asymptotic_giant_branch` |
| 5 | end of the HB track | `early_asymptotic_giant_branch` |

#### Physical parameters

| Parameter | Role | Value / source | Notes |
|---|---|---|---|
| `initial_mass` | axis (varies across the published grid) | file values `initial_mass` | initial masses of the track files present in this set (stated by the filenames) |
| `initial_z` | fixed (known value for the whole product) | file value `initial_z` | initial metallicity Z, stated by the zip/directory name (e.g. Z0.0001Y0.249) |
| `initial_helium` | fixed (known value for the whole product) | file value `initial_helium` | initial helium fraction Y, stated by the zip/directory name next to Z |
| `initial_rotation` | not applicable under this physics | — | PARSEC v1.2S tracks are non-rotating |
| `mixing_length` | implicit (used by the model, not recoverable) | — | not_reported |

### Scientific references

- Bressan, A., Marigo, P., Girardi, L., et al. 2012, MNRAS, 427, 127 (bibcode `2012MNRAS.427..127B`)
- Marigo, P., Bressan, A., Nanni, A., Girardi, L., Pumo, M. L. 2013, MNRAS, 434, 488 (bibcode `2013MNRAS.434..488M`)
- Marigo, P., Girardi, L., Bressan, A., et al. 2017, ApJ, 835, 77 (bibcode `2017ApJ...835...77M`)
- Chen, Y., Girardi, L., Bressan, A., et al. 2014, MNRAS, 444, 2525 and 2015, MNRAS, 452, 1068
- Pastorelli, G., et al. 2019, MNRAS, 485, 5666 and 2020, MNRAS
