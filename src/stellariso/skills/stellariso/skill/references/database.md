# The local database

Read this file before building, completing, moving, or merging a local
database, or when choosing how much disk the build uses.

## Concept

There is no implicit cache location. A database is a directory you name
explicitly, built once from what the sources publish — MIST as complete
official packages (about 16.5 GB for the isochrone products), PARSEC as
form-computed tables through the official CMD web form — and queried
fully offline afterwards (`database=` everywhere). Re-running the build
completes whatever is missing; already verified products are never
re-fetched or overwritten.

```python
import stellariso

stellariso.build_database("path/to/db", dry_run=True)   # the plan, with sizes
db = stellariso.build_database("path/to/db")            # build or complete
db = stellariso.open_database("path/to/db")             # read-only open
```

`build_database` keyword arguments:

- `models=` limits the build to given families (`"mist"`,
  `"parsec"`); default is all families.
- `dry_run=True` reports missing parts per product and touches nothing.
- `extract=False` keeps only the official archives (the complete,
  self-contained backup): a product is extracted on first open, after
  the archive's sha256 is verified against the recorded value — the
  right mode when the disk cannot hold every package extracted at once.
- `verify_existing=False` classifies present files without re-hashing
  them (the rebuild-trust knob).
- `form_pause=` seconds waited after every CMD form submission
  (default 5; the service is a small public host).

## Querying a database

```python
db.products_for("mist", "1.2")                          # ProductRecord tuple
grid = db.grid("mist/1.2", label="vvcrit0.4_full_isos")  # IsochroneGrid
mist = stellariso.construct("mist/1.2", database=db, label="vvcrit0.4_full_isos")
db.describe()                                           # human summary
db.provenance("mist/1.2")                               # full provenance object
```

`model` is version-qualified; when a release holds several products,
`label=` picks one (the alternative labels are listed on ambiguity).

## What a database contains

- Per product: the downloaded archive, the extracted files, and a
  `MANIFEST.json` recording the exact URL, sha256, size, retrieval
  time, file-format notes, and the literature to cite.
- At the root: an inventory (`database.json`), a human `README.md`
  with format notes and citations, a snapshot of the unified-parameters
  documentation, and the two-state status report
  (`db_status.md` / `db_status.json` — each product complete or
  incomplete, part by part, measured against the declared design).
- The whole database, or any subset of its product directories, is
  portable: copy it to another machine and `open_database` works there.

## Moving and merging

```python
stellariso.merge_database("subset-db", "target-db")   # pure-copy merge channel
stellariso.refresh_database("target-db")             # regenerate root artifacts
```

`merge_database` copies selected products in through a verified
pure-copy channel (checksums compared; conflicts reported, never
overwritten silently). `refresh_database` regenerates the root
inventory, README, and status report from the products present.

The export/rsync/verify machinery (`tools/db_transfer.py` — export
plans with per-file checksums, an assembled rsync command, receiving-
side verification, manifest-schema upgrades) and the status CLI
(`tools/db_status.py`) ship with the repository checkout, not with the
installed package; in an installed-package context use the Python API
above.
