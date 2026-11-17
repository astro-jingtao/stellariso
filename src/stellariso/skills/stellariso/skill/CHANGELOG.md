# Changelog — stellariso

Notable changes, newest first. Format: skill-forge `templates/changelog.md`.

## 2026-11-17

### Changed
- Padova composition selection corrected to the native coordinate: `initial_z` (plus `overshoot` for padova/2000), not `[Fe/H]`. Each family's selection axes are its own native publication coordinates (MIST publishes [Fe/H]; PARSEC and Padova publish Z); Padova's [Fe/H] = log10(Z/Z_ref) is a recorded derived parameter, never a selection axis.
- The padova/1994 phase rules are now described as stellariso-derived shape rules (empirically locked on the full archive; the source documents no stage classification), replacing "documented shape rules".
- Role statement names all three families (MIST, PARSEC, legacy Padova).

## 2026-11-12

### Added
- Legacy Padova family coverage — padova/1994 (Bertelli+ 1994 VizieR tables) and padova/2000 (Girardi+ 2000): construct/open_grid usage, [Fe/H] as the composition coordinate (declared Z-to-[Fe/H] conversion per release), the padova/2000 `overshoot` axis, derived-field semantics (FLUM-inverted initial mass, Mwind branch, Mbol zero point, gravity closure), and the per-release phase-classification rules (isochsum characteristic points for 2000, documented shape rules for 1994).

## 2026-10-18

### Added
- Initial release of the stellariso usage skill, shipped as package data inside the stellariso package (never deployed by the installation itself).
- Point-query workflow — construct, get/get_detailed, convenience getters, selection and interpolation semantics, phase queries, the audit record.
- Two-layer reference — open_grid, grid selection, native and unified layers, parameter roles, provenance, custom-coordinate interpolation.
- Local-database reference — build, open, query, merge, refresh, archives-only mode, portability.
- PARSEC CMD web-form reference — CmdFormClient, CmdFieldSet, acquisition records, politeness, hand-obtained tables.
- Deployment guide (`skills/SKILL-DEPLOY.md`) and the `stellariso.skill_directory()` package API for locating the skill on any installation.
