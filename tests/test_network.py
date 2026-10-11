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

    def test_parsec_track_archives_resolve(self):
        session = requests.Session()
        session.trust_env = False
        # stev.oapd.inaf.it's chain omits its intermediate CA; verify with
        # the bundled intermediate (mirrors the builder's default session)
        from stellariso.database import _ca_bundle
        from stellariso.models import catalog as cat

        bundle = _ca_bundle(
            Path(__file__).parent / "data" / "tls-check", "parsec",
            cat("parsec")["ca_bundle"],
        )
        session.verify = str(bundle)
        for release in cat("parsec")["releases"]:
            for product in release["products"]:
                resp = session.head(product["url"], timeout=_HEAD_TIMEOUT, allow_redirects=True)
                assert resp.status_code == 200, (product["url"], resp.status_code)
