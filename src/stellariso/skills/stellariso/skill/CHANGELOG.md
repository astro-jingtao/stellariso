# Changelog — stellariso

Notable changes, newest first. Format: skill-forge `templates/changelog.md`.

## 2026-10-18

### Added
- Initial release of the stellariso usage skill, shipped as package data inside the stellariso package (never deployed by the installation itself).
- Point-query workflow — construct, get/get_detailed, convenience getters, selection and interpolation semantics, phase queries, the audit record.
- Two-layer reference — open_grid, grid selection, native and unified layers, parameter roles, provenance, custom-coordinate interpolation.
- Local-database reference — build, open, query, merge, refresh, archives-only mode, portability.
- PARSEC CMD web-form reference — CmdFormClient, CmdFieldSet, acquisition records, politeness, hand-obtained tables.
- Deployment guide (`skills/SKILL-DEPLOY.md`) and the `stellariso.skill_directory()` package API for locating the skill on any installation.
