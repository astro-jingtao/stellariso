"""The local isochrone database: unified, family-agnostic management.

A database is one user-chosen directory built once by ``build_database``
acquiring the complete published matrix — official packages where the
source publishes them, and the declared products of the source's official
computation service (the PARSEC CMD web form) where that is the only
channel — and queried afterwards by ``open_database`` fully offline.
There is no environment-variable lookup and no implicit location: every
entry point takes ``database`` explicitly.

Layout::

    <database>/
        database.json                # inventory of every product
        README.md                    # human summary, format notes, citations
        unified-parameters.md        # mapping documentation snapshot
        db_status.md / db_status.json  # two-state scan report (all families)
        <family>/<collection>/<label>/
            MANIFEST.json            # schema stellariso-manifest/2
            <archive>.txz            # package products: the archive, kept
            <extracted data files>   #   plus the on-demand extraction
            output.dat               # form products (blueprint cells): the
            output.dat.record.json   #   log-age table and its record, plus
            output_linear.dat        #   the linear young-age refinement
            output_linear.dat.record.json
        export/<name>/               # export plans (travel with the database)

Module layout (import from the concrete module, never the package root)::

    core.py        Database / open_database / ProductRecord — the read side
    design.py      designs, parts, verdicts, the FamilyAdapter base,
                   selection criteria, the adapter registry
    manifest.py    MANIFEST v2 read/write, the read-only legacy bridge,
                   the whole-database manifest upgrade
    scan.py        the two-state scanner and the db_status reports
    build.py       build_database — the universal acquisition loop
    transfer.py    merge_database, export plans, verify, rsync assembly
    inventory.py   regeneration of the database-root derived artifacts

Self-containment: each MANIFEST records what the data is, where it came
from, its checksum, the file format, and the literature to cite, so the
database stays interpretable with the upstream websites gone. Only
relative paths are stored — the whole database, or any subset of its
product directories, can be copied to another machine and opened there.
"""
