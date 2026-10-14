"""Offline tests for the CMD web-form request layer.

Live behavior (a real submission) is covered by the network-marked test in
tests/test_network.py; everything here runs against captured fixtures
(tests/data/parsec/cmd_form/) and stub sessions.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from stellariso.exceptions import CmdFormError
from stellariso.models.parsec.cmd_form import (
    CGI_FIELD_NAMES,
    CMD_FORM_URL,
    CMD_ENDPOINTS,
    DEFAULT_FIELDS,
    CmdFieldSet,
    CmdFormClient,
    _parse_result_page,
    form_field_names,
)

FIXTURES = Path(__file__).parent.parent / "data" / "parsec" / "cmd_form"
RESULT_PAGE = (FIXTURES / "result_page.html").read_text(encoding="utf-8")
TABLE = (FIXTURES / "output_table.dat").read_bytes()
EMPTY_TABLE = (FIXTURES / "output_empty.dat").read_bytes()


class _StubResponse:
    def __init__(self, content: bytes = b"", text: str = ""):
        self.content = content
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        return None


class _StubSession:
    """Answers GET/POST from canned payloads; records what was sent."""

    def __init__(self, form_html: str = "", result_html: str = ""):
        self.form_html = form_html
        self.result_html = result_html
        self.downloads: dict[str, bytes] = {}
        self.posts: list[tuple[str, list]] = []

    def get(self, url, timeout=None):
        if url in self.downloads:
            return _StubResponse(content=self.downloads[url])
        assert url == CMD_FORM_URL, f"unexpected GET {url}"
        return _StubResponse(text=self.form_html)

    def post(self, url, files=None, timeout=None):
        assert url == CMD_ENDPOINTS["3.9"], f"unexpected POST {url}"
        self.posts.append((url, files))
        return _StubResponse(text=self.result_html)


def _mini_form(without: str = "") -> str:
    """A synthetic form page declaring the payload's controls (minus one).

    Documented format-equivalent synthetic HTML (fixture README): exercises
    the name extraction including the noise it must skip (a <meta name=>
    attribute, a reset button). ``without`` drops one control to simulate
    upstream drift.
    """
    names = [n for n in DEFAULT_FIELDS if n not in ("submit_form", without)]
    controls = "".join(f'<input name="{n}">' for n in names)
    return (
        '<!DOCTYPE html><html><head><meta name="robots" content="noarchive">'
        "</head><body><form>"
        + controls
        + '<input type="submit" name="reset_form" value="Back to input form">'
        + '<input type="submit" name="submit_form" value="Submit">'
        "</form></body></html>"
    )


class TestCmdFieldSet:
    def test_default_covers_full_inventory(self):
        field_set = CmdFieldSet.from_overrides()
        assert field_set.as_dict() == DEFAULT_FIELDS

    def test_override_applies(self):
        field_set = CmdFieldSet.from_overrides(isoc_dlage="0.5")
        assert field_set.as_dict()["isoc_dlage"] == "0.5"

    def test_unknown_name_rejected(self):
        with pytest.raises(ValueError, match="unknown CMD form field"):
            CmdFieldSet.from_overrides(lagelow="9.0")  # pre-isoc_ stale name

    def test_incomplete_payload_rejected(self):
        partial = {k: v for k, v in DEFAULT_FIELDS.items() if k != "isoc_zlow"}
        with pytest.raises(ValueError, match="empty tables"):
            CmdFieldSet.from_overrides(partial)

    def test_multipart_pairs_carry_cgifields_protocol(self):
        pairs = CmdFieldSet.from_overrides().multipart_pairs()
        assert pairs[-len(CGI_FIELD_NAMES):] == [
            (".cgifields", n) for n in CGI_FIELD_NAMES
        ]
        assert [n for n, _ in pairs[: -len(CGI_FIELD_NAMES)]] == list(DEFAULT_FIELDS)
        assert pairs[0] == ("cmd_version", "3.9")


class TestFormFieldNames:
    def test_extracts_controls_and_skips_noise(self):
        names = form_field_names(_mini_form())
        assert set(DEFAULT_FIELDS) - {"submit_form"} <= names
        assert "robots" not in names
        assert "reset_form" not in names
        assert "submit_form" not in names

    def test_select_and_unquoted_names_extracted(self):
        html = "<form><select name=pick_one><option>x</option></select></form>"
        assert form_field_names(html) == {"pick_one"}


class TestParseResultPage:
    def test_real_page_facts(self):
        facts = _parse_result_page(RESULT_PAGE, CMD_ENDPOINTS["3.9"])
        assert facts["output_name"] == "output680835736989.dat"
        assert facts["output_url"] == (
            "https://stev.oapd.inaf.it/tmp/output680835736989.dat"
        )
        assert facts["submitted_at"] == "Wed Oct 14 15:19:37 UTC 2026"
        assert facts["completed_at"] == "Wed Oct 14 15:19:45 UTC 2026"
        assert facts["retention_note"] == "2 h"

    def test_warning_text_raises(self):
        page = RESULT_PAGE.replace(
            '<p class="warning"></p>', '<p class="warning">something is off</p>'
        )
        with pytest.raises(CmdFormError, match="something is off"):
            _parse_result_page(page, CMD_ENDPOINTS["3.9"])

    def test_error_line_raises(self):
        page = RESULT_PAGE.replace(
            "<fieldset title='Results'>",
            "Error: Selected photometric system is not available.<fieldset title='Results'>",
        )
        with pytest.raises(CmdFormError, match="photometric system"):
            _parse_result_page(page, CMD_ENDPOINTS["3.9"])

    def test_missing_output_link_raises(self):
        page = RESULT_PAGE.replace(
            "<a href=../tmp/output680835736989.dat>output680835736989.dat</a>", ""
        )
        with pytest.raises(CmdFormError, match="no output link"):
            _parse_result_page(page, CMD_ENDPOINTS["3.9"])


class TestSubmitOffline:
    def test_submit_returns_job_with_exact_payload(self):
        session = _StubSession(form_html=_mini_form(), result_html=RESULT_PAGE)
        client = CmdFormClient(session=session)
        job = client.submit(CmdFieldSet.from_overrides(isoc_dlage="0.5"))
        assert job.fields["isoc_dlage"] == "0.5"
        assert job.fields["cmd_version"] == "3.9"
        # the multipart body carried fields + the .cgifields protocol
        url, files = session.posts[0]
        assert url == CMD_ENDPOINTS["3.9"]
        assert files[-len(CGI_FIELD_NAMES):] == [
            (".cgifields", (None, n)) for n in CGI_FIELD_NAMES
        ]

    def test_drift_against_live_form_caught_before_submission(self):
        # the form dropped a field our payload still sends (upstream rename)
        session = _StubSession(form_html=_mini_form(without="imf_file"), result_html=RESULT_PAGE)
        client = CmdFormClient(session=session)
        with pytest.raises(CmdFormError, match="imf_file"):
            client.submit(CmdFieldSet.from_overrides())
        assert session.posts == []

    def test_unknown_version_rejected(self):
        with pytest.raises(ValueError, match="unknown CMD version"):
            CmdFormClient(cmd_version="2.0")


class TestFetchOutput:
    def _client_with_output(self, content: bytes) -> tuple[CmdFormClient, _StubSession]:
        session = _StubSession(form_html=_mini_form(), result_html=RESULT_PAGE)
        session.downloads["https://stev.oapd.inaf.it/tmp/output680835736989.dat"] = content
        return CmdFormClient(session=session), session

    def test_download_pin_and_record(self):
        client, _ = self._client_with_output(TABLE)
        job = client.submit(CmdFieldSet.from_overrides())
        out = client.fetch_output(job)
        assert out.n_data_rows == 30
        assert out.sha256 == hashlib.sha256(TABLE).hexdigest()
        assert out.content == TABLE
        record = out.record()
        assert record["cmd_version"] == "3.9"
        assert record["request_fields"] == DEFAULT_FIELDS
        assert record["output"]["n_data_rows"] == 30
        assert record["output"]["sha256"] == out.sha256
        # the server's own echo is part of the record
        release = [ln for ln in record["server_header_echo"] if "PARSEC release" in ln]
        assert release and "v1.2S" in release[0]

    def test_header_only_output_refused(self):
        client, _ = self._client_with_output(EMPTY_TABLE)
        job = client.submit(CmdFieldSet.from_overrides())
        with pytest.raises(CmdFormError, match="0 data rows"):
            client.fetch_output(job)
