"""Generate the PARSEC form-product section of models/parsec/catalog.json.

The matrix exhausts every option combination that changes the computed
isochrones, at the widest, finest age-metallicity coverage the form
supports (see docs/cmd-form.md for the wire protocol and the option
semantics):

- Track sets: every (track_parsec, track_colibri) pair the form accepts,
  each over its full documented [M/H] window. Photometry is a
  placeholder only (stellariso consumes the physical columns): the
  verified YBC UBVRIJHK baseline for the sets served by YBC tables, and
  the OBC/odfnew LSST system for the older sets the YBC library does not
  carry ("Photometric system still not available among YBC tables").
- Ages: log10 6.6 to 10.13. The current physics sets (v1.2S web COLIBRI
  chain, v2.0) use the fine step 0.02 dex (~177 ages per composition);
  secondary sets use 0.05 dex; option-variation products use 0.1 dex.
  The form computes intermediate ages by its own interpolation, so
  finer steps add smoothness, not independent model content.
- Compositions: one product per [M/H] value on a 0.1 dex grid (single
  value per job - the server's range arithmetic drops end points
  through floating point, so ranges are never used for metallicity).
- Option variations (IMF, LPV prescription, Reimers eta, TP-cycle
  resolution) change only auxiliary columns (int_IMF; period0-4/pmode)
  or one continuous physics knob; each value is fetched once at a
  representative composition and age grid instead of multiplying the
  whole matrix.
- Interstellar extinction is fixed at A_V = 0: verified not to change
  any physical column (docs/cmd-form.md). Circumstellar dust and the
  bolometric-correction version affect magnitudes only and stay at the
  baseline.

Run:  python tools/generate_parsec_form_catalog.py   (rewrites the file)
"""

from __future__ import annotations

import json
from pathlib import Path

CATALOG = Path(__file__).parent.parent / "src" / "stellariso" / "models" / "parsec" / "catalog.json"

AGE_FINE = ("6.6", "10.13", "0.02")
AGE_COARSE = ("6.6", "10.13", "0.05")
AGE_AUX = ("6.6", "10.13", "0.1")

MH_AUX = "0.0"  # representative composition for option variations

STATIC = {
    "family": "parsec",
    "channel": "form",
    "ca_bundle": "ZeroSSLRSADVSSLCA2.crt",
    "source_note": (
        "PARSEC publishes no isochrone packages: the official CMD web form "
        "(https://stev.oapd.inaf.it/cgi-bin/cmd) computes isochrone tables "
        "server-side on request and is the isochrone acquisition channel "
        "(scriptable with a complete current field set, verified live "
        "2026-10-14; complete wire documentation: docs/cmd-form.md). The "
        "host's TLS chain omits its intermediate CA (ZeroSSL RSA DV SSL CA "
        "2); the bundled intermediate completes the chain so verification "
        "stays on."
    ),
    "scope_note": (
        "Form-computed isochrone products (request-layer client: "
        "stellariso.models.parsec.cmd_form). Every track-set combination "
        "the form accepts, over its full [M/H] window, on a 0.1 dex "
        "composition grid and fine log-age grids; option variations that "
        "change only auxiliary columns are fetched once each at a "
        "representative composition. Historical pre-2006 tracks on "
        "pleiadi.oapd.inaf.it remain out of scope."
    ),
    "matrix_notes": {
        "ages": "log10(age/yr) 6.6-10.13; 0.02 dex for the current physics sets, 0.05 dex for secondary sets, 0.1 dex for option variations; the server interpolates intermediate ages itself",
        "metallicities": "one product per [M/H] on a 0.1 dex grid (single-value jobs; range end points are unreliable server-side)",
        "photometry": "placeholder only: YBC UBVRIJHK for YBC-served sets, OBC/odfnew LSST for the older sets (the YBC library does not carry them)",
        "extinction": "A_V = 0 everywhere; extinction changes magnitudes only (verified 2026-10-15, docs/cmd-form.md)",
        "skipped_options": "dust compositions and bolometric-correction versions affect magnitudes only; kind_postagb has a single accepted value; v1.1/v1.0 outputs carry no release echo (identity release 'unknown')",
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
    {
        "release": "v1.2S +  COLIBRI S_35",
        "release_dir": "v1.2S_COLIBRI_S35",
        "fields": {
            "track_parsec": "parsec_CAF09_v1.2S",
            "track_colibri": "parsec_CAF09_v1.2S_S35",
            "photsys_version": "odfnew",
            "photsys_file": "tab_mag_odfnew/tab_mag_lsst.dat",
        },
        "mh_values": [round(-1.4 + 0.1 * k, 1) for k in range(18)],
        "age_grid": AGE_COARSE,
        "label_prefix": "",
        "verify_header": "PARSEC release v1.2S +  COLIBRI S_35",
    },
    {
        "release": "v1.2S +  COLIBRI S_07",
        "release_dir": "v1.2S_COLIBRI_S07",
        "fields": {
            "track_parsec": "parsec_CAF09_v1.2S",
            "track_colibri": "parsec_CAF09_v1.2S_S07",
            "photsys_version": "odfnew",
            "photsys_file": "tab_mag_odfnew/tab_mag_lsst.dat",
        },
        "mh_values": [round(-1.4 + 0.1 * k, 1) for k in range(18)],
        "age_grid": AGE_COARSE,
        "label_prefix": "",
        "verify_header": "PARSEC release v1.2S +  COLIBRI S_07",
    },
    {
        "release": "v1.2S + COLIBRI release PR16, as in Marigo et al. 2017",
        "release_dir": "v1.2S_COLIBRI_PR16",
        "fields": {
            "track_parsec": "parsec_CAF09_v1.2S",
            "track_colibri": "parsec_CAF09_v1.2S_NOV13",
            "photsys_version": "odfnew",
            "photsys_file": "tab_mag_odfnew/tab_mag_lsst.dat",
        },
        "mh_values": [round(-2.2 + 0.1 * k, 1) for k in range(28)],
        "age_grid": AGE_COARSE,
        "label_prefix": "",
        "verify_header": "PARSEC release v1.2S + COLIBRI release PR16",
    },
    {
        "release": "v1.2S",
        "release_dir": "v1.2S_no_colibri",
        "fields": {
            "track_parsec": "parsec_CAF09_v1.2S",
            "track_colibri": "no",
            "photsys_version": "odfnew",
            "photsys_file": "tab_mag_odfnew/tab_mag_lsst.dat",
        },
        "mh_values": [round(-2.2 + 0.1 * k, 1) for k in range(28)],
        "age_grid": AGE_COARSE,
        "label_prefix": "",
        "verify_header": "PARSEC release v1.2S",
    },
    {
        "release": "unknown",
        "release_dir": "v1.1",
        "fields": {
            "track_parsec": "parsec_CAF09_v1.1",
            "track_colibri": "no",
            "photsys_version": "odfnew",
            "photsys_file": "tab_mag_odfnew/tab_mag_lsst.dat",
        },
        "mh_values": [round(-2.2 + 0.1 * k, 1) for k in range(28)],
        "age_grid": AGE_COARSE,
        "label_prefix": "v1.1_",
        "verify_header": None,
    },
    {
        "release": "unknown",
        "release_dir": "v1.0",
        "fields": {
            "track_parsec": "parsec_CAF09_v1.0",
            "track_colibri": "no",
            "photsys_version": "odfnew",
            "photsys_file": "tab_mag_odfnew/tab_mag_lsst.dat",
        },
        "mh_values": [round(-1.5 + 0.1 * k, 1) for k in range(22)],
        "age_grid": AGE_COARSE,
        "label_prefix": "v1.0_",
        "verify_header": None,
    },
]

#: Option variations at one representative composition: each value of the
#: discrete auxiliary options (IMF, LPV) and each probing value of the
#: continuous physics knobs (Reimers eta, TP-cycle resolution).
AUX_BASE = {
    "track_parsec": "parsec_CAF09_v1.2S",
    "track_colibri": "parsec_CAF09_v1.2S_S_LMC_08_web",
    "photsys_version": "YBCnewVega",
    "photsys_file": "YBC_tab_mag_odfnew/tab_mag_ubvrijhk.dat",
}
AUX_RELEASE = SETS[0]
AUX_VARIANTS = [
    ("aux_imf_salpeter", {"imf_file": "tab_imf/imf_salpeter.dat"}),
    ("aux_imf_chabrier_exponential", {"imf_file": "tab_imf/imf_chabrier_exponential.dat"}),
    ("aux_imf_chabrier_lognormal", {"imf_file": "tab_imf/imf_chabrier_lognormal.dat"}),
    ("aux_imf_chabrier_lognormal_salpeter", {"imf_file": "tab_imf/imf_chabrier_lognormal_salpeter.dat"}),
    ("aux_lpv1_trabucchi2017", {"kind_LPV": "1"}),
    ("aux_lpv2_trabucchi2019", {"kind_LPV": "2"}),
    ("aux_lpv3_trabucchi2021fm", {"kind_LPV": "3"}),
    ("aux_eta_reimers_0.0", {"eta_reimers": "0.0"}),
    ("aux_eta_reimers_0.4", {"eta_reimers": "0.4"}),
    ("aux_n_tpc_5", {"n_inTPC": "5"}),
    ("aux_n_tpc_20", {"n_inTPC": "20"}),
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
    entry = {
        "release": spec["release"],
        "release_dir": spec["release_dir"],
        "age_grid": {
            "log_age_low": spec["age_grid"][0],
            "log_age_upp": spec["age_grid"][1],
            "log_age_step": spec["age_grid"][2],
        },
        "products": products,
    }
    if spec is AUX_RELEASE:
        for label, variant in AUX_VARIANTS:
            fields = {
                **AUX_BASE,
                **variant,
                **_age_fields(AGE_AUX),
                "isoc_ismetlog": "1",
                "isoc_metlow": MH_AUX,
                "isoc_metupp": MH_AUX,
                "isoc_dmet": "0",
            }
            entry["products"].append(
                _product(label, fields, AUX_RELEASE["verify_header"])
            )
    return entry


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
