"""Request layer for the Padova CMD isochrone web form.

The form at https://stev.oapd.inaf.it/cgi-bin/cmd computes isochrone
tables server-side: a multipart POST to the versioned CGI endpoint
(``cmd_3.9``) runs the job synchronously (seconds to minutes) and answers
with an HTML page linking the output table under ``/tmp/``, which the
server retains for about 2 h. This module speaks that wire and nothing
else: field names, defaults, and endpoint names are the form's own
vocabulary, and every submission returns the exact ordered payload plus
the response facts, so the caller can archive complete provenance. The
output file's own ``#`` header independently echoes the release chain
("isochrones based on PARSEC release v1.2S +  COLIBRI S_37 + S_35 +
PR16"), the CMD version, and the physics switches — record both; the
server's echo is authoritative, the payload is what was asked for.

Two wire facts this layer encodes because they were learned the hard way:

- The payload must be the COMPLETE current field set (the one exception:
  an unchecked ``output_gzip`` is legitimately absent — the ``.cgifields``
  protocol below covers it). Submissions carrying
  stale field names (the pre-``isoc_`` vocabulary) or partial sets are
  accepted and run, but yield header-only tables — zero data rows, no
  error message (verified 2026-10-11). The CGI checkbox protocol requires
  every checkbox name to be listed in ``.cgifields`` (repeated field)
  whether checked or not, so the CGI can tell "unchecked" from "absent".
  :class:`CmdFieldSet` therefore validates against the full inventory
  and the form's own value vocabulary (closed option sets, numeric
  bounds, ordered ranges; captured 2026-10-15) before anything is sent,
  :meth:`CmdFormClient.submit` re-checks the
  payload against the live form's field names when ``check_form`` is on,
  and :meth:`CmdFormClient.fetch_output` refuses empty tables after
  download.
- The host's TLS chain omits its intermediate CA, so the bundled
  intermediate (``ZeroSSLRSADVSSLCA2.crt`` next to this module) is added
  to the trust store in memory — verification stays on.

No automatic retries: a retry re-runs a server-side job; retrying is the
caller's decision.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import urljoin

import certifi
import requests

from stellariso.exceptions import CmdFormError
from stellariso.warnings import CmdFormDriftWarning, CmdFormOptionWarning

__all__ = [
    "CMD_FORM_URL",
    "CMD_ENDPOINTS",
    "CGI_FIELD_NAMES",
    "DEFAULT_FIELDS",
    "RADIO_VALUES",
    "SELECT_VALUES",
    "IMF_FILES",
    "NUMERIC_BOUNDS",
    "CmdFieldSet",
    "CmdFormClient",
    "CmdJob",
    "CmdOutput",
    "form_field_names",
]

CMD_FORM_URL = "https://stev.oapd.inaf.it/cgi-bin/cmd"
CMD_ENDPOINTS = {
    "3.9": "https://stev.oapd.inaf.it/cgi-bin/cmd_3.9",
}

_HOST = "https://stev.oapd.inaf.it"

#: Checkbox names the CGI wants declared in .cgifields entries (repeated
#: multipart field), checked or not — the CGI.pm convention for telling
#: "unchecked" apart from "absent".
CGI_FIELD_NAMES = (
    "dust_sourceC",
    "dust_sourceM",
    "extinction_coeff",
    "extinction_curve",
    "isoc_isagelog",
    "isoc_ismetlog",
    "kind_LPV",
    "output_gzip",
    "output_kind",
    "photsys_version",
    "track_colibri",
    "track_parsec",
    "track_postagb",
)

#: The complete baseline payload: every field, with the values of a
#: verified successful browser submission (2026-10-14, PARSEC v1.2S +
#: COLIBRI S_LMC_08_web, UBVRIJHK YBC magnitudes, isochrone tables,
#: single isochrone at 1e9 yr, Z = 0.0152). Order as the browser sends it.
DEFAULT_FIELDS: dict[str, str] = {
    "cmd_version": "3.9",
    "track_omegai": "0.00",
    "track_parsec": "parsec_CAF09_v1.2S",
    "track_colibri": "parsec_CAF09_v1.2S_S_LMC_08_web",
    "track_postagb": "no",
    "n_inTPC": "10",
    "eta_reimers": "0.2",
    "kind_interp": "1",
    "kind_postagb": "-1",
    "photsys_file": "YBC_tab_mag_odfnew/tab_mag_ubvrijhk.dat",
    "photsys_version": "YBCnewVega",
    "dust_sourceM": "dpmod60alox40",
    "dust_sourceC": "AMCSIC15",
    "kind_mag": "2",
    "kind_dust": "0",
    "extinction_av": "0.0",
    "extinction_coeff": "constant",
    "extinction_curve": "cardelli",
    "kind_LPV": "4",
    "imf_file": "tab_imf/imf_kroupa_orig.dat",
    "isoc_isagelog": "0",
    "isoc_agelow": "1.0e9",
    "isoc_ageupp": "1.0e10",
    "isoc_dage": "0.0",
    "isoc_lagelow": "6.6",
    "isoc_lageupp": "10.13",
    "isoc_dlage": "0.0",
    "isoc_ismetlog": "0",
    "isoc_zlow": "0.0152",
    "isoc_zupp": "0.03",
    "isoc_dz": "0.0",
    "isoc_metlow": "-2",
    "isoc_metupp": "0.3",
    "isoc_dmet": "0.0",
    "output_kind": "0",
    "output_evstage": "1",
    "lf_maginf": "-15",
    "lf_magsup": "20",
    "lf_deltamag": "0.5",
    "sim_mtot": "1.0e4",
    "submit_form": "Submit",
}

# Every field the baseline declares is required in every payload; the
# checkbox output_gzip is the one OPTIONAL field (an unchecked CGI.pm
# checkbox is simply absent — .cgifields declares it either way). Its
# checked wire form ("1") was verified live 2026-10-15: the job is
# accepted and the output arrives gzipped.
_REQUIRED_FIELDS = frozenset(DEFAULT_FIELDS)
_SUPPORTED_FIELDS = _REQUIRED_FIELDS | frozenset({"output_gzip"})

#: Closed value sets the live form declares for its radio/select controls
#: and fixed hidden switches (captured 2026-10-15; docs/cmd-form.md).
RADIO_VALUES: dict[str, frozenset[str]] = {
    "cmd_version": frozenset({"3.9"}),
    "track_parsec": frozenset(
        {"parsec_CAF09_v2.0", "parsec_CAF09_v1.2S", "parsec_CAF09_v1.1",
         "parsec_CAF09_v1.0"}
    ),
    "track_colibri": frozenset(
        {"parsec_CAF09_v1.2S_S_LMC_08_web", "parsec_CAF09_v1.2S_S35",
         "parsec_CAF09_v1.2S_S07", "parsec_CAF09_v1.2S_NOV13", "no"}
    ),
    "track_postagb": frozenset({"no"}),
    "photsys_version": frozenset({"YBC", "YBCnewVega", "odfnew"}),
    "dust_sourceM": frozenset(
        {"nodustM", "sil", "AlOx", "dpmod60alox40", "dpmod"}
    ),
    "dust_sourceC": frozenset({"nodustC", "gra", "AMC", "AMCSIC15"}),
    "kind_interp": frozenset({"1"}),
    "kind_postagb": frozenset({"-1"}),
    "kind_mag": frozenset({"2"}),
    "kind_dust": frozenset({"0"}),
    "extinction_coeff": frozenset({"constant"}),
    "extinction_curve": frozenset({"cardelli"}),
    "kind_LPV": frozenset({"1", "2", "3", "4"}),
    "isoc_isagelog": frozenset({"0", "1"}),
    "isoc_ismetlog": frozenset({"0", "1"}),
    "output_kind": frozenset({"0", "1", "3", "4"}),
    "output_evstage": frozenset({"1"}),
    "output_gzip": frozenset({"1"}),
}

#: The single-value selects, verbatim from the captured form.
IMF_FILES = (
    "tab_imf/imf_salpeter.dat",
    "tab_imf/imf_chabrier_exponential.dat",
    "tab_imf/imf_chabrier_lognormal.dat",
    "tab_imf/imf_chabrier_lognormal_salpeter.dat",
    "tab_imf/imf_kroupa_orig.dat",
)
SELECT_VALUES: dict[str, tuple[str, ...]] = {
    "imf_file": IMF_FILES,
    "photsys_file": (
        # 104 systems under tab_mag_odfnew/ and YBC_tab_mag_odfnew/
        "tab_mag_odfnew/tab_mag_.dat",
        "YBC_tab_mag_odfnew/tab_mag_2mass_spitzer.dat",
        "YBC_tab_mag_odfnew/tab_mag_2mass_spitzer_wise.dat",
        "YBC_tab_mag_odfnew/tab_mag_2mass.dat",
        "YBC_tab_mag_odfnew/tab_mag_ogle_2mass_spitzer.dat",
        "YBC_tab_mag_odfnew/tab_mag_ubvrijhk.dat",
        "YBC_tab_mag_odfnew/tab_mag_bessell.dat",
        "YBC_tab_mag_odfnew/tab_mag_akari.dat",
        "YBC_tab_mag_odfnew/tab_mag_batc.dat",
        "YBC_tab_mag_odfnew/tab_mag_megacam_wircam.dat",
        "YBC_tab_mag_odfnew/tab_mag_wircam.dat",
        "YBC_tab_mag_odfnew/tab_mag_megacam_post2014.dat",
        "YBC_tab_mag_odfnew/tab_mag_megacam.dat",
        "YBC_tab_mag_odfnew/tab_mag_ciber.dat",
        "tab_mag_odfnew/tab_mag_ciber2.dat",
        "YBC_tab_mag_odfnew/tab_mag_clue_galex.dat",
        "YBC_tab_mag_odfnew/tab_mag_CSST.dat",
        "YBC_tab_mag_odfnew/tab_mag_decam.dat",
        "YBC_tab_mag_odfnew/tab_mag_denis.dat",
        "YBC_tab_mag_odfnew/tab_mag_dmc14.dat",
        "YBC_tab_mag_odfnew/tab_mag_dmc15.dat",
        "YBC_tab_mag_odfnew/tab_mag_eis.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfi.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfi2.dat",
        "YBC_tab_mag_odfnew/tab_mag_euclid_nisp.dat",
        "YBC_tab_mag_odfnew/tab_mag_galex_sloan.dat",
        "YBC_tab_mag_odfnew/tab_mag_galex.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaia_tycho2_2mass.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaiaDR2_tycho2_2mass.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaiaDR2weiler_tycho2_2mass.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaiaEDR3.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaia.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaiaDR2.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaiaDR2maiz.dat",
        "YBC_tab_mag_odfnew/tab_mag_gaiaDR2weiler.dat",
        "YBC_tab_mag_odfnew/tab_mag_UVbright.dat",
        "YBC_tab_mag_odfnew/tab_mag_acs_hrc.dat",
        "YBC_tab_mag_odfnew/tab_mag_acs_wfc_pos04jul06.dat",
        "YBC_tab_mag_odfnew/tab_mag_acs_wfc_202101.dat",
        "tab_mag_odfnew/tab_mag_acs_wfc3_nircam.dat",
        "YBC_tab_mag_odfnew/tab_mag_nicmosab.dat",
        "YBC_tab_mag_odfnew/tab_mag_nicmosvega.dat",
        "YBC_tab_mag_odfnew/tab_mag_stis.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfc3_wideverywide.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfc3_202101_verywide.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfc3_202101_medium.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfc3_202101_wide.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfpc2.dat",
        "YBC_tab_mag_odfnew/tab_mag_hipparcos.dat",
        "YBC_tab_mag_odfnew/tab_mag_int_wfc.dat",
        "YBC_tab_mag_odfnew/tab_mag_iphas.dat",
        "tab_mag_odfnew/tab_mag_jpas.dat",
        "YBC_tab_mag_odfnew/tab_mag_jwst_miri_wide.dat",
        "tab_mag_odfnew/tab_mag_jwst_narrow.dat",
        "YBC_tab_mag_odfnew/tab_mag_jwst_nircam_miri_wide.dat",
        "tab_mag_odfnew/tab_mag_jwst_nircam_wide.dat",
        "tab_mag_odfnew/tab_mag_jwst_nircam_widemedium_dec23.dat",
        "tab_mag_odfnew/tab_mag_jwst_nircam_widemedium_nov22.dat",
        "tab_mag_odfnew/tab_mag_jwst_nircam_widemedium.dat",
        "YBC_tab_mag_odfnew/tab_mag_jwst_niriss_nov22.dat",
        "tab_mag_odfnew/tab_mag_jwst_nirspec.dat",
        "tab_mag_odfnew/tab_mag_jwst_fnl.dat",
        "YBC_tab_mag_odfnew/tab_mag_kepler.dat",
        "YBC_tab_mag_odfnew/tab_mag_kepler_2mass.dat",
        "YBC_tab_mag_odfnew/tab_mag_vst_vista.dat",
        "YBC_tab_mag_odfnew/tab_mag_lbt_lbc.dat",
        "YBC_tab_mag_odfnew/tab_mag_lsst_wfirst_proposed2017.dat",
        "tab_mag_odfnew/tab_mag_lsstR1.9_gaiaEDR3_euclid_Roman2024.dat",
        "tab_mag_odfnew/tab_mag_lsst.dat",
        "tab_mag_odfnew/tab_mag_lsstDP0.dat",
        "tab_mag_odfnew/tab_mag_lsstR1.9.dat",
        "YBC_tab_mag_odfnew/tab_mag_nmbs.dat",
        "YBC_tab_mag_odfnew/tab_mag_noao_ctio_mosaic2.dat",
        "YBC_tab_mag_odfnew/tab_mag_ogle.dat",
        "YBC_tab_mag_odfnew/tab_mag_PLATO.dat",
        "YBC_tab_mag_odfnew/tab_mag_panstarrs1.dat",
        "tab_mag_odfnew/tab_mag_Roman2021.dat",
        "tab_mag_odfnew/tab_mag_Roman2024.dat",
        "tab_mag_odfnew/tab_mag_splus.dat",
        "YBC_tab_mag_odfnew/tab_mag_sloan.dat",
        "YBC_tab_mag_odfnew/tab_mag_sloan_2mass.dat",
        "YBC_tab_mag_odfnew/tab_mag_sloan_ukidss.dat",
        "YBC_tab_mag_odfnew/tab_mag_swift_uvot.dat",
        "YBC_tab_mag_odfnew/tab_mag_skymapper.dat",
        "YBC_tab_mag_odfnew/tab_mag_spitzer.dat",
        "YBC_tab_mag_odfnew/tab_mag_stroemgren.dat",
        "YBC_tab_mag_odfnew/tab_mag_hsc.dat",
        "YBC_tab_mag_odfnew/tab_mag_suprimecam.dat",
        "tab_mag_odfnew/tab_mag_SuperBIT.dat",
        "YBC_tab_mag_odfnew/tab_mag_TESS_2mass.dat",
        "YBC_tab_mag_odfnew/tab_mag_TESS_2mass_kepler.dat",
        "YBC_tab_mag_odfnew/tab_mag_ukidss.dat",
        "YBC_tab_mag_odfnew/tab_mag_unions.dat",
        "YBC_tab_mag_odfnew/tab_mag_uvit.dat",
        "YBC_tab_mag_odfnew/tab_mag_vertecs.dat",
        "YBC_tab_mag_odfnew/tab_mag_visir.dat",
        "YBC_tab_mag_odfnew/tab_mag_vista.dat",
        "YBC_tab_mag_odfnew/tab_mag_vphas.dat",
        "YBC_tab_mag_odfnew/tab_mag_vst_omegacam.dat",
        "YBC_tab_mag_odfnew/tab_mag_vilnius.dat",
        "YBC_tab_mag_odfnew/tab_mag_wfc3_uvisCaHK.dat",
        "YBC_tab_mag_odfnew/tab_mag_washington_ddo51.dat",
        "YBC_tab_mag_odfnew/tab_mag_ztf.dat",
        "YBC_tab_mag_odfnew/tab_mag_deltaa.dat",
    ),
}

#: Free-text numeric fields: (minimum, maximum or None); value must parse
#: as a number and lie inside the bounds. Range pairs additionally
#: require low <= upp and a non-negative step.
NUMERIC_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "track_omegai": (0.0, 0.99),
    "n_inTPC": (1, None),
    "eta_reimers": (0.0, 1.0),
    "extinction_av": (0.0, None),
    "lf_maginf": (None, None),
    "lf_magsup": (None, None),
    "lf_deltamag": (0.0, None),
    "sim_mtot": (0.0, None),
    "isoc_agelow": (0.0, None),
    "isoc_ageupp": (0.0, None),
    "isoc_dage": (0.0, None),
    "isoc_lagelow": (None, None),
    "isoc_lageupp": (None, None),
    "isoc_dlage": (0.0, None),
    "isoc_zlow": (0.0, None),
    "isoc_zupp": (0.0, None),
    "isoc_dz": (0.0, None),
    "isoc_metlow": (None, None),
    "isoc_metupp": (None, None),
    "isoc_dmet": (0.0, None),
}
_RANGE_PAIRS = (
    ("isoc_agelow", "isoc_ageupp", "isoc_dage"),
    ("isoc_lagelow", "isoc_lageupp", "isoc_dlage"),
    ("isoc_zlow", "isoc_zupp", "isoc_dz"),
    ("isoc_metlow", "isoc_metupp", "isoc_dmet"),
    ("lf_maginf", "lf_magsup", None),
)
_INTEGER_FIELDS = frozenset({"n_inTPC"})


def _validate_values(merged: dict[str, str]) -> None:
    """Value-level validation against the captured form's own vocabulary.

    Closed-set fields accept only declared values; numeric fields must
    parse and respect bounds; range families need low <= upp and a
    non-negative step. Advisories (upstream-documented combinations that
    are accepted but pointless) warn instead of failing.
    """
    import warnings

    for name, allowed in RADIO_VALUES.items():
        if name in merged and merged[name] not in allowed:
            raise ValueError(
                f"CMD form field {name!r} does not take {merged[name]!r}; "
                f"declared values: {sorted(allowed)}"
            )
    for name, allowed in SELECT_VALUES.items():
        if name in merged and merged[name] not in allowed:
            raise ValueError(
                f"CMD form field {name!r} does not take {merged[name]!r}; "
                f"it must be one of the {len(allowed)} declared files "
                f"(IMF_FILES / SELECT_VALUES[{name!r}])"
            )
    for name, (lo, hi) in NUMERIC_BOUNDS.items():
        if name not in merged:
            continue
        try:
            value = float(merged[name])
        except ValueError:
            raise ValueError(
                f"CMD form field {name!r} must be numeric, got "
                f"{merged[name]!r}"
            ) from None
        if name in _INTEGER_FIELDS and float(merged[name]) != int(value):
            raise ValueError(f"CMD form field {name!r} must be an integer")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise ValueError(
                f"CMD form field {name!r}={merged[name]!r} outside the "
                f"form's range [{lo}, {hi}]"
            )
    for low, upp, step in _RANGE_PAIRS:
        if float(merged[low]) > float(merged[upp]):
            raise ValueError(
                f"CMD form range {low}={merged[low]!r} exceeds "
                f"{upp}={merged[upp]!r}"
            )
        if step is not None and float(merged[step]) < 0:
            raise ValueError(
                f"CMD form step {step}={merged[step]!r} must be >= 0 "
                "(0 selects a single value)"
            )

    track = merged["track_parsec"]
    if track != "parsec_CAF09_v2.0":
        if float(merged["track_omegai"]) != 0.0:
            warnings.warn(
                "track_omegai applies only to PARSEC v2.0 tracks; the "
                f"selected set {track!r} ignores it",
                CmdFormOptionWarning,
                stacklevel=3,
            )
    else:
        if merged["eta_reimers"] != DEFAULT_FIELDS["eta_reimers"]:
            warnings.warn(
                "Reimers mass loss is not applied on PARSEC v2.0 tracks; "
                "eta_reimers has no effect for this track set",
                CmdFormOptionWarning,
                stacklevel=3,
            )
        if float(merged["extinction_av"]) != 0.0:
            warnings.warn(
                "star-by-star interstellar extinction does not work on "
                "the rotating PARSEC v2.0 models (upstream statement); "
                "the magnitudes will not carry it",
                CmdFormOptionWarning,
                stacklevel=3,
            )
    if track != "parsec_CAF09_v1.2S" and merged["track_colibri"] != "no":
        warnings.warn(
            "COLIBRI options apply only to PARSEC v1.2S tracks; the "
            f"selected set {track!r} ignores them",
            CmdFormOptionWarning,
            stacklevel=3,
        )
    if float(merged["eta_reimers"]) > 0.5:
        warnings.warn(
            "eta_reimers > 0.5 exceeds the range upstream calls "
            "well-tested ('mass loss works fine as long as eta < 0.5; "
            "check the results for higher values')",
            CmdFormOptionWarning,
            stacklevel=3,
        )


@dataclass(frozen=True)
class CmdFieldSet:
    """One complete, validated CMD form payload (the form's own names).

    Built from :data:`DEFAULT_FIELDS` plus overrides; every override name
    must be a field the current form defines, every value must be one the
    form's own vocabulary declares (closed sets, numeric bounds, ordered
    ranges), and the result must still cover the full inventory — the
    payload defects that make the CGI silently return header-only tables
    or run a job that ignores what was asked for.
    """

    values: tuple[tuple[str, str], ...]

    @classmethod
    def from_overrides(
        cls, base: Mapping[str, str] | None = None, /, **overrides
    ) -> "CmdFieldSet":
        merged: dict[str, str] = dict(base if base is not None else DEFAULT_FIELDS)
        unknown = sorted(set(overrides) - _SUPPORTED_FIELDS)
        if unknown:
            raise ValueError(
                f"unknown CMD form field(s) {unknown}; the form defines "
                f"{sorted(_SUPPORTED_FIELDS)}"
            )
        merged.update({name: str(value) for name, value in overrides.items()})
        missing = sorted(_REQUIRED_FIELDS - set(merged))
        if missing:
            raise ValueError(
                f"incomplete CMD form payload, missing {missing}; the CGI "
                "accepts incomplete payloads but answers with empty tables"
            )
        _validate_values(merged)
        # wire order: the verified baseline order, optional extras
        # inserted before the pressed submit button (which stays last)
        ordered = [k for k in DEFAULT_FIELDS if k in merged and k != _SUBMIT_BUTTON]
        ordered += [k for k in merged if k not in DEFAULT_FIELDS]
        if _SUBMIT_BUTTON in merged:
            ordered.append(_SUBMIT_BUTTON)
        return cls(values=tuple((k, merged[k]) for k in ordered))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> "CmdFieldSet":
        return cls.from_overrides({}, **dict(mapping))

    def as_dict(self) -> dict[str, str]:
        return dict(self.values)

    def multipart_pairs(self) -> list[tuple[str, str]]:
        """The exact multipart sequence: fields, then the .cgifields list."""
        return list(self.values) + [(".cgifields", n) for n in CGI_FIELD_NAMES]


@dataclass(frozen=True)
class CmdJob:
    """A completed form submission, with everything the server stated."""

    cmd_version: str
    endpoint: str
    fields: dict[str, str]
    submitted_at: str
    completed_at: str
    output_url: str
    output_name: str
    retention_note: str

    def record(self) -> dict:
        """The submission half of an acquisition record (JSON-ready)."""
        return {
            "cmd_version": self.cmd_version,
            "endpoint": self.endpoint,
            "form_url": CMD_FORM_URL,
            "request_fields": dict(self.fields),
            "job_submitted_at": self.submitted_at,
            "job_completed_at": self.completed_at,
            "output_url": self.output_url,
            "server_retention": self.retention_note,
        }


@dataclass(frozen=True)
class CmdOutput:
    """A downloaded output table, pinned by checksum."""

    job: CmdJob
    url: str
    filename: str
    content: bytes
    sha256: str
    retrieved_at: str
    comment_lines: tuple[str, ...] = field(default=())
    n_data_rows: int = 0

    def text(self) -> str:
        """The table decoded (gunzipped when the payload is gzip)."""
        if self.content[:2] == b"\x1f\x8b":
            return gzip.decompress(self.content).decode("utf-8", "replace")
        return self.content.decode("utf-8", "replace")

    def record(self) -> dict:
        """The full acquisition record: request, response, file, echo."""
        rec = self.job.record()
        rec["retrieved_at"] = self.retrieved_at
        rec["output"] = {
            "filename": self.filename,
            "url": self.url,
            "sha256": self.sha256,
            "size_bytes": len(self.content),
            "n_data_rows": self.n_data_rows,
        }
        rec["server_header_echo"] = list(self.comment_lines)
        return rec


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_CONTROL_TAG_RE = re.compile(r"<(input|select|textarea)\b([^>]*)>", re.I)
_NAME_ATTR_RE = re.compile(r"""name=["']?([A-Za-z0-9_.]+)""")
_TYPE_ATTR_RE = re.compile(r"""type=["']?([A-Za-z]+)""")

#: submit/reset buttons appear in the form but not in submissions (only
#: the pressed button is sent); the payload's own pressed button is this.
_SUBMIT_BUTTON = "submit_form"


def form_field_names(form_html: str) -> set[str]:
    """Field names the form's HTML input controls declare (drift detection).

    Buttons and non-control ``name=`` attributes (``<meta name=...>``) are
    excluded: they are not payload fields.
    """
    names: set[str] = set()
    for tag, attrs in _CONTROL_TAG_RE.findall(form_html):
        if tag.lower() == "input":
            t = _TYPE_ATTR_RE.search(attrs)
            if t and t.group(1).lower() in ("submit", "reset", "button", "image"):
                continue
        m = _NAME_ATTR_RE.search(attrs)
        if m:
            names.add(m.group(1))
    return names


# -- result page ---------------------------------------------------------------

_WARNING_RE = re.compile(r'<p class="warning">(.*?)</p>', re.S)
_ERROR_LINE_RE = re.compile(r"\bError:\s*[^<\n]+")
_SUBMITTED_RE = re.compile(r"job was submitted on (.*?)\s*<")
_COMPLETED_RE = re.compile(r"job was completed on (.*?)\s*[.<]")
_OUTPUT_LINK_RE = re.compile(
    r"""href=['"]?(\.\./tmp/(output\d+\.dat(?:\.gz)?))['"]?"""
)
_RETENTION_RE = re.compile(r"will be deleted in ([^<]*?) from now")


def _parse_result_page(html: str, endpoint: str) -> dict:
    """Extract the job facts from a CMD result page, loudly.

    Any warning text, any 'Error:' line, or a missing output link raises
    :class:`CmdFormError` — the form's silent failure modes must not pass.
    """
    m = _WARNING_RE.search(html)
    if m and m.group(1).strip():
        raise CmdFormError(f"CMD form warning: {m.group(1).strip()}")
    m = _ERROR_LINE_RE.search(html)
    if m:
        raise CmdFormError(f"CMD form error: {m.group(0).strip()}")
    if _OUTPUT_LINK_RE.search(html) is None:
        raise CmdFormError(
            "CMD form result page carries no output link; page head: "
            + re.sub(r"\s+", " ", html[:300])
        )
    return {
        "submitted_at": _search(_SUBMITTED_RE, html, "submission timestamp"),
        "completed_at": _search(_COMPLETED_RE, html, "completion timestamp"),
        "output_name": _OUTPUT_LINK_RE.search(html).group(2),
        "output_url": urljoin(endpoint, _OUTPUT_LINK_RE.search(html).group(1)),
        "retention_note": _search(_RETENTION_RE, html, "retention note"),
    }


def _search(regex: re.Pattern, text: str, what: str) -> str:
    m = regex.search(text)
    if m is None:
        raise CmdFormError(f"CMD form result page lacks the {what}")
    return m.group(1).strip()


# -- client --------------------------------------------------------------------


class _IntermediateChainAdapter(requests.adapters.HTTPAdapter):
    """Verify against certifi plus the bundled intermediate, in memory."""

    def __init__(self, intermediate_pem: str, **kwargs):
        self._intermediate_pem = intermediate_pem
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(cafile=certifi.where())
        context.load_verify_locations(cadata=self._intermediate_pem)
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def _default_session() -> requests.Session:
    from stellariso import __version__

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": f"stellariso/{__version__} (CMD form client)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": CMD_FORM_URL,
        }
    )
    intermediate = Path(__file__).parent / "ZeroSSLRSADVSSLCA2.crt"
    session.mount(_HOST, _IntermediateChainAdapter(intermediate.read_text(encoding="ascii")))
    return session


class CmdFormClient:
    """Submits the CMD form and fetches the computed table.

    Parameters mirror the wire: ``cmd_version`` selects the endpoint,
    ``submit_timeout`` / ``download_timeout`` bound the synchronous job
    and the output download, and ``check_form`` GETs the form before
    submitting to verify the payload names against the live form (the
    upstream once renamed the isochrone range fields; stale payloads run
    fine and return empty tables).
    """

    def __init__(
        self,
        cmd_version: str = "3.9",
        session: requests.Session | None = None,
        submit_timeout: float = 900.0,
        download_timeout: float = 300.0,
        check_form: bool = True,
    ):
        if cmd_version not in CMD_ENDPOINTS:
            raise ValueError(
                f"unknown CMD version {cmd_version!r}; known: {sorted(CMD_ENDPOINTS)}"
            )
        self.cmd_version = cmd_version
        self.endpoint = CMD_ENDPOINTS[cmd_version]
        self.session = session if session is not None else _default_session()
        self.submit_timeout = submit_timeout
        self.download_timeout = download_timeout
        self.check_form = check_form

    def fetch_form(self) -> str:
        """The form page HTML (field-name reference, not a login step)."""
        resp = self.session.get(CMD_FORM_URL, timeout=self.download_timeout)
        resp.raise_for_status()
        return resp.text

    def submit(self, fields: CmdFieldSet | Mapping[str, str]) -> CmdJob:
        """Run one form submission; returns the completed job."""
        field_set = (
            fields
            if isinstance(fields, CmdFieldSet)
            else CmdFieldSet.from_mapping(fields)
        )
        if self.check_form:
            self._check_against_live_form(field_set)
        resp = self.session.post(
            self.endpoint,
            files=[(name, (None, value)) for name, value in field_set.multipart_pairs()],
            timeout=self.submit_timeout,
        )
        resp.raise_for_status()
        facts = _parse_result_page(resp.text, self.endpoint)
        return CmdJob(
            cmd_version=self.cmd_version,
            endpoint=self.endpoint,
            fields=field_set.as_dict(),
            **facts,
        )

    def fetch_output(self, job: CmdJob) -> CmdOutput:
        """Download the job's table; refuses header-only (empty) outputs.

        The zero-row refusal is the guard for the form's silent failure
        mode: an accepted job whose payload did not match the current
        form still 'succeeds' — with no data and no error.
        """
        resp = self.session.get(job.output_url, timeout=self.download_timeout)
        resp.raise_for_status()
        content = resp.content
        text = (
            gzip.decompress(content).decode("utf-8", "replace")
            if content[:2] == b"\x1f\x8b"
            else content.decode("utf-8", "replace")
        )
        lines = text.splitlines()
        data_rows = sum(
            1 for ln in lines if ln.strip() and not ln.lstrip().startswith("#")
        )
        if data_rows == 0:
            raise CmdFormError(
                f"CMD form returned a header-only table (0 data rows) for "
                f"{job.output_name}: the job was accepted but produced "
                "nothing — typically a payload that does not match the "
                "current form field set, or request ranges no model covers"
            )
        return CmdOutput(
            job=job,
            url=job.output_url,
            filename=job.output_name,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            retrieved_at=_now_iso(),
            comment_lines=tuple(ln for ln in lines if ln.lstrip().startswith("#")),
            n_data_rows=data_rows,
        )

    def _check_against_live_form(self, field_set: CmdFieldSet) -> None:
        live = form_field_names(self.fetch_form())
        payload_names = set(field_set.as_dict()) - {_SUBMIT_BUTTON}
        stale = sorted(payload_names - live)
        if stale:
            raise CmdFormError(
                f"payload carries field(s) {stale} the live form no longer "
                "defines; the CGI would accept the job and return an empty "
                "table — update the field set (upstream renamed fields "
                "once already: the isoc_ prefix)"
            )
        extra = sorted(
            n
            for n in live - set(field_set.as_dict())
            if not n.startswith(".") and n not in CGI_FIELD_NAMES
        )
        if extra:
            import warnings

            warnings.warn(
                f"live form declares field(s) {extra} the payload does not "
                "send; if any is required upstream the job will come back "
                "empty (fetch_output refuses that case loudly)",
                CmdFormDriftWarning,
                stacklevel=3,
            )
