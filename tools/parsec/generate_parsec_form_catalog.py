"""Generate the PARSEC form-product section of models/parsec/catalog.json.

The catalog's parsec section is the registry of the form-computed products
the reference database still archives. The 2026-10-15/16 fetch archived 206
products (every track-set combination over its full [M/H] window, plus
one-shot option-variation tables); the 2026-10-16 blueprint redesign
disowned the coarse-age secondary grids and the option variations, the
local database pruned them, and this registry keeps only what is on disk:
the two primary track sets at their full [M/H] extent on the fine log-age
step — each product being the log-age half of a fetch-stage blueprint
cell. The exact payloads of the pruned products remain recoverable from
this file's git history.

The ACQUISITION DESIGN is declared elsewhere —
stellariso.models.parsec.blueprint (docs/parsec/blueprint.md) fixes the
full cell space (secondary sets, rotation, eta/dust/LPV/n_inTPC axes, and
the linear young-age halves), and stellariso.models.parsec.build builds
it — so this file is not the build driver; it stays the archived-product
registry, and this generator is the mechanism that rewrites it
consistently.

Shape of what remains (see docs/parsec/cmd-form.md for the wire protocol
and the option semantics):

- The two primary sets: the v1.2S web COLIBRI chain and v2.0 (at omega_i
  = 0), each over its full [M/H] window on a 0.1 dex grid, one product
  per composition (single value per job — the server's range arithmetic
  drops end points through floating point, so ranges are never used for
  metallicity). Ages log10 6.6 to 10.13 at the fine step 0.02 dex (~177
  ages per composition).
- Photometry is a placeholder only (stellariso consumes the physical
  columns): the verified YBC UBVRIJHK baseline both sets are served by.
- Interstellar extinction is A_V = 0 throughout: verified not to change
  any physical column (docs/parsec/cmd-form.md). Circumstellar dust, the
  LPV prescription, Reimers eta, and the TP-cycle resolution sit at their
  canonical values; the blueprint declares them as designed cell axes.

Run:  python tools/parsec/generate_parsec_form_catalog.py   (rewrites the file)
"""

from __future__ import annotations

import json
from pathlib import Path

CATALOG = Path(__file__).parent.parent.parent / "src" / "stellariso" / "models" / "parsec" / "catalog.json"

AGE_FINE = ("6.6", "10.13", "0.02")

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
        "Registry of the form-computed products still archived in the "
        "reference database (request-layer client: "
        "stellariso.models.parsec.cmd_form): the two primary track sets at "
        "their full [M/H] extent on a 0.1 dex grid, one fine-step log-age "
        "table per composition - each product is the log-age half of a "
        "blueprint cell. The coarse-grid secondary products and one-shot "
        "option-variation tables of the 2026-10-15/16 fetch were pruned on "
        "2026-10-16, when the blueprint redesign disowned them; their exact "
        "payloads remain in this file's git history. The declared "
        "acquisition design - the full cell space the build completes "
        "towards, secondary sets and all axes included - lives in "
        "stellariso.models.parsec.blueprint (docs/parsec/blueprint.md). "
        "Historical pre-2006 tracks on pleiadi.oapd.inaf.it remain out of "
        "scope."
    ),
    "matrix_notes": {
        "ages": "log10(age/yr) 6.6-10.13 at the fine step 0.02 dex (~177 ages per composition); the linear young-age half of each cell is a blueprint-builder acquisition archived beside the log table",
        "metallicities": "one product per [M/H] on a 0.1 dex grid (single-value jobs; range end points are unreliable server-side)",
        "photometry": "placeholder only: YBC UBVRIJHK for the YBC-served sets (the archived pairs both are)",
        "extinction": "A_V = 0 everywhere; extinction changes magnitudes only (verified 2026-10-15, docs/parsec/cmd-form.md)",
        "archived_options": "the archived products keep circumstellar dust, the LPV prescription, Reimers eta, and the TP-cycle resolution at their canonical values; the blueprint declares them as designed cell axes",
    },
}

#: (release echo, release_dir, track fields, photometry fields,
#:  [M/H] grid, age grid, label prefix)
SETS = [
    {
        "release": "v1.2S +  COLIBRI S_37 + S_35 + PR16",
        "release_dir": "v1.2S_COLIBRI_web",
        "fields": {
            "track_parsec": "parsec_CAF09_v1.2S",
            "track_colibri": "parsec_CAF09_v1.2S_S_LMC_08_web",
            "photsys_version": "YBCnewVega",
            "photsys_file": "YBC_tab_mag_odfnew/tab_mag_ubvrijhk.dat",
        },
        "mh_values": [round(-2.2 + 0.1 * k, 1) for k in range(28)],
        "age_grid": AGE_FINE,
        "label_prefix": "",
        "verify_header": "PARSEC release v1.2S +  COLIBRI S_37 + S_35 + PR16",
    },
    {
        "release": "v2.0",
        "release_dir": "v2.0",
        "fields": {
            "track_parsec": "parsec_CAF09_v2.0",
            "track_colibri": "no",
            "track_omegai": "0.00",
            "photsys_version": "YBCnewVega",
            "photsys_file": "YBC_tab_mag_odfnew/tab_mag_ubvrijhk.dat",
        },
        "mh_values": [round(-2.1 + 0.1 * k, 1) for k in range(25)],
        "age_grid": AGE_FINE,
        "label_prefix": "",
        "verify_header": "PARSEC release v2.0",
    },
]


def _mh_label(mh: float) -> str:
    return f"mh_{'m' if mh < 0 else 'p'}{abs(mh):.1f}"


def _product(label: str, fields: dict, verify: str | None) -> dict:
    return {
        "label": label,
        "kind": "cmd_form_isochrones",
        "fields": {k: str(v) for k, v in fields.items()},
        "verify_header": verify,
        "format": "cmd_table_3_9",
    }


def _age_fields(grid) -> dict:
    low, upp, step = grid
    return {
        "isoc_isagelog": "1",
        "isoc_lagelow": low,
        "isoc_lageupp": upp,
        "isoc_dlage": step,
    }


def _release_entry(spec: dict) -> dict:
    products = []
    for mh in spec["mh_values"]:
        fields = {
            **spec["fields"],
            **_age_fields(spec["age_grid"]),
            "isoc_ismetlog": "1",
            "isoc_metlow": f"{mh:.1f}",
            "isoc_metupp": f"{mh:.1f}",
            "isoc_dmet": "0",
        }
        products.append(
            _product(spec["label_prefix"] + _mh_label(mh), fields, spec["verify_header"])
        )
    return {
        "release": spec["release"],
        "release_dir": spec["release_dir"],
        "age_grid": {
            "log_age_low": spec["age_grid"][0],
            "log_age_upp": spec["age_grid"][1],
            "log_age_step": spec["age_grid"][2],
        },
        "products": products,
    }


def main() -> None:
    catalog = dict(STATIC)
    catalog["releases"] = [_release_entry(spec) for spec in SETS]
    n = sum(len(r["products"]) for r in catalog["releases"])
    CATALOG.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {CATALOG} with {n} products in {len(SETS)} releases")


if __name__ == "__main__":
    main()
