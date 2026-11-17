"""Live-network smoke tests (run explicitly: pytest -m network).

These verify that every URL in the packaged release catalogs still
resolves upstream. They download nothing beyond HEAD requests.
"""

from __future__ import annotations

import pytest
import requests

from stellariso.models import catalog

pytestmark = pytest.mark.network

_HEAD_TIMEOUT = 60


class TestCatalogUrlsLive:
    def test_every_catalog_url_resolves(self):
        # direct connection: the test verifies the upstream, not the local
        # proxy configuration (a degraded local proxy must not read as a
        # dead upstream link)
        session = requests.Session()
        session.trust_env = False
        failures = []
        checked = 0
        for family in ("mist",):
            for release in catalog(family)["releases"]:
                for product in release["products"]:
                    url = product["url"]
                    resp = session.head(url, timeout=_HEAD_TIMEOUT, allow_redirects=True)
                    checked += 1
                    if resp.status_code != 200:
                        failures.append((url, resp.status_code))
        assert checked > 0
        assert not failures, f"dead catalog URLs: {failures}"


class TestPadovaArchiveLive:
    def test_build_and_open_the_padova_products(self, tmp_path):
        # the two VizieR archive products are small enough to actually
        # build live (~3.2 MB total): fetch, MANIFEST, checksums, and a
        # real grid open — the acquisition design's end-to-end check
        import stellariso

        db = stellariso.build_database(tmp_path, models=["padova"])
        for model, n in (("padova/1994", 297), ("padova/2000", 350)):
            grid = db.grid(model, label="vizier_tables")
            assert len(grid) == n
        manifest = (
            tmp_path / "padova" / "1994" / "vizier_tables" / "MANIFEST.json"
        ).read_text(encoding="utf-8")
        assert "4c43fe832694e2041e8b71bf750772ba672cf61a44d18111adec294b079d067f" in manifest
        assert "J/A+AS/106/275" in manifest
        iso = db.grid("padova/2000", label="vizier_tables").get_isochrone(
            method="exact", log_age=9.0, initial_z=0.019, overshoot=1.0
        )
        assert iso.unified["phase"][0] == "main_sequence"


class TestCmdFormLive:
    def test_submit_single_isochrone_end_to_end(self):
        # one smallest-possible job: the complete default field set asks for
        # a single isochrone (1e9 yr, Z = 0.0152); the server computes it
        # synchronously in seconds. Also proves the honest (non-browser)
        # User-Agent is served real tables, not header-only output.
        from stellariso.models.parsec.cmd_form import CmdFieldSet, CmdFormClient

        client = CmdFormClient()
        job = client.submit(CmdFieldSet.from_overrides())
        out = client.fetch_output(job)
        assert out.n_data_rows > 100  # a real isochrone, not the empty mode
        record = out.record()
        assert record["cmd_version"] == "3.9"
        assert any("isochrones based on PARSEC release" in ln for ln in record["server_header_echo"])
