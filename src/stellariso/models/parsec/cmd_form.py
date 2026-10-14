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

- The payload must be the COMPLETE current field set. Submissions carrying
  stale field names (the pre-``isoc_`` vocabulary) or partial sets are
  accepted and run, but yield header-only tables — zero data rows, no
  error message (verified 2026-10-11). The CGI checkbox protocol requires
  every checkbox name to be listed in ``.cgifields`` (repeated field)
  whether checked or not, so the CGI can tell "unchecked" from "absent".
  :class:`CmdFieldSet` therefore validates against the full inventory
  before anything is sent, :meth:`CmdFormClient.submit` re-checks the
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
from stellariso.warnings import CmdFormDriftWarning

__all__ = [
    "CMD_FORM_URL",
    "CMD_ENDPOINTS",
    "CGI_FIELD_NAMES",
    "DEFAULT_FIELDS",
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

# The empty-table failure mode is specific to incomplete payloads; gzip
# output (output_gzip) is deliberately not settable — its checked-value
# wire form is unverified, and the plain .dat is what the reader takes.
_SUPPORTED_FIELDS = frozenset(DEFAULT_FIELDS)


@dataclass(frozen=True)
class CmdFieldSet:
    """One complete, validated CMD form payload (the form's own names).

    Built from :data:`DEFAULT_FIELDS` plus overrides; every override name
    must be a field the current form defines, and the result must still
    cover the full inventory — the two payload defects that make the CGI
    silently return header-only tables.
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
        missing = sorted(_SUPPORTED_FIELDS - set(merged))
        if missing:
            raise ValueError(
                f"incomplete CMD form payload, missing {missing}; the CGI "
                "accepts incomplete payloads but answers with empty tables"
            )
        return cls(values=tuple(merged.items()))

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
