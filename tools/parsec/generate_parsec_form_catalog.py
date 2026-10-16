"""Generate the PARSEC form-product registry of models/parsec/catalog.json.

The catalog's parsec section registers the form-computed products of the
current fetch stage: one product per blueprint cell, carrying the cell's
exact log-age submission fields, so every registered request is replayable
as-is (``CmdFieldSet.from_overrides(**fields)``). The registry is derived
mechanically from the declared acquisition blueprint
(``stellariso.models.parsec.blueprint``, docs/parsec/blueprint.md), so it
cannot drift from the design it registers. The builder consumes the
blueprint, not this registry: this file is the form channel's family-catalog
face — channel, CA bundle, source notes, and the product registry — the way
the package families' catalogs are the face of theirs.

What it registers (wire protocol and option semantics:
docs/parsec/cmd-form.md):

- every designed track set at the stage's [M/H] extent: primary sets at
  full extent, secondary sets at their sparse initial slice (anchor
  compositions plus window edges);
- the stage's axis values: Reimers eta at 0.0/0.2/0.4 where the axis
  applies (canonical where inert), initial rotation at every designed
  omega_i for v2.0 and 0 elsewhere, n_inTPC/dust/LPV at canonical values;
- one fine-step log-age table per cell (~177 isochrones); the linear
  young-age half of each cell is a blueprint-builder acquisition archived
  beside the log table.

Run:  python tools/parsec/generate_parsec_form_catalog.py   (rewrites the file)
"""

from __future__ import annotations

import json
from pathlib import Path

from stellariso.models.parsec import blueprint as bp

CATALOG = Path(__file__).parent.parent.parent / "src" / "stellariso" / "models" / "parsec" / "catalog.json"

STATIC = {
    "family": "parsec",
    "channel": "form",
    "ca_bundle": "ZeroSSLRSADVSSLCA2.crt",
    "source_note": (
        "PARSEC publishes no isochrone packages: the official CMD web form "
        "(https://stev.oapd.inaf.it/cgi-bin/cmd) computes isochrone tables "
        "server-side on request and is the isochrone acquisition channel "
        "(scriptable with a complete current field set, verified live "
        "2026-10-14; complete wire documentation: docs/parsec/cmd-form.md). "
        "The host's TLS chain omits its intermediate CA (ZeroSSL RSA DV SSL "
        "CA 2); the bundled intermediate completes the chain so verification "
        "stays on."
    ),
    "scope_note": (
        "Registry of the form-computed products of the current fetch stage "
        "(request-layer client: stellariso.models.parsec.cmd_form): every "
        "product is the log-age half of one blueprint cell, carrying that "
        "half's exact submission fields, and the linear young-age half is "
        "archived beside it by the blueprint builder. The declared "
        "acquisition design - the full cell space the build completes "
        "towards, fetch stages and all axes - lives in "
        "stellariso.models.parsec.blueprint (docs/parsec/blueprint.md). "
        "Historical pre-2006 tracks on pleiadi.oapd.inaf.it remain out of "
        "scope."
    ),
    "matrix_notes": {
        "ages": "log10(age/yr) 6.6-10.13 at the fine step 0.02 dex (177 isochrones per product); each cell's linear young-age half (1.0e5 to 4.0e6 yr by 1.0e5, 40 isochrones) is a blueprint-builder acquisition archived beside the log table",
        "metallicities": "one product per [M/H] point of the set's designed grid (0.1 dex steps plus exact window edges; single-value jobs - the server's range arithmetic drops range end points); secondary sets are registered at their sparse initial slice (anchors -1.0, 0.0, +0.3 plus window edges) until their completion stage",
        "photometry": "placeholder only: YBC UBVRIJHK for the two YBC-served sets, OBC odfnew+LSST for the six sets YBC serves no tables for (stellariso consumes the physical columns)",
        "extinction": "A_V = 0 everywhere; extinction changes magnitudes only (verified 2026-10-15, docs/parsec/cmd-form.md)",
        "stage_axes": "Reimers eta at 0.0/0.2/0.4 where the axis applies (canonical 0.2 where inert); initial rotation at every designed omega_i for v2.0 (11 values), 0 elsewhere; n_inTPC, circumstellar dust, and LPV prescription at their canonical values - designed axes whose remaining values are later stages",
    },
}


def _release_entry(ts: bp.TrackSet) -> dict:
    products = []
    for cell in bp.fetch_cells(ts):
        entry = {
            "label": cell.label,
            "kind": "cmd_form_isochrones",
            "fields": cell.log_fields(),
        }
        if ts.verify_header:
            entry["verify_header"] = ts.verify_header
        entry["format"] = "cmd_table_3_9"
        products.append(entry)
    return {
        "release": ts.release,
        "release_dir": ts.key,
        "age_grid": {
            "log_age_low": bp.LOG_AGE_GRID[0],
            "log_age_upp": bp.LOG_AGE_GRID[1],
            "log_age_step": bp.LOG_AGE_GRID[2],
        },
        "products": products,
    }


def main() -> None:
    catalog = dict(STATIC)
    catalog["releases"] = [_release_entry(ts) for ts in bp.TRACK_SETS.values()]
    n = sum(len(r["products"]) for r in catalog["releases"])
    CATALOG.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {CATALOG} with {n} products in {len(catalog['releases'])} releases")


if __name__ == "__main__":
    main()
