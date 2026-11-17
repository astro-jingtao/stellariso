# tools/

Repository-level command-line entries. None of these ship with the
installed package — its full functionality, including every database
operation below, lives in the `stellariso` library; the tools only add
the command-line form.

## generator/

Regenerators of repository and package-data artifacts from their
declarative sources:

- `generate_parameter_docs.py` — renders `docs/unified-parameters.md`
  from the unified-parameter registry. Run after every registry edit;
  a test keeps the document and the registry in sync.
- `generate_parsec_form_catalog.py` — regenerates the PARSEC release
  catalog (`models/parsec/catalog.json`, shipped as package data) from
  the acquisition blueprint. Only PARSEC has a generator by design:
  its catalog spans 471 form-computed cells derived mechanically from
  the blueprint, while the MIST and Padova catalogs are hand-maintained
  declarations of a handful of published products — there the catalog
  itself is the source of truth, with no upstream design object to
  generate from.

## database/

Build, inspect, and move local databases (CLI forms of the
`stellariso.database` machinery):

- `build_database.py` — build or complete a database for any selection
  of families: download the declared packages (MIST, Padova) and submit
  the declared form jobs (PARSEC).
- `db_status.py` — the two-state completion report over every family's
  declared design (`db_status.md`/`.json`).
- `db_transfer.py` — export, rsync, merge, verify, refresh, and
  migrate-manifests: the database move/merge transport.
- `fetch_parsec_isochrones.py` — one CMD form submission outside any
  database build (table + full acquisition record).
- `check_mist_physics.py`, `check_padova_physics.py` — physics
  spot-checks over any isochrone files a database holds (closure
  relations, mass monotonicity, inversion residuals).
