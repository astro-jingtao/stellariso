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
        failures = []
        checked = 0
        for family in ("mist",):
            for release in catalog(family)["releases"]:
                for product in release["products"]:
                    url = product["url"]
                    resp = requests.head(url, timeout=_HEAD_TIMEOUT, allow_redirects=True)
                    checked += 1
                    if resp.status_code != 200:
                        failures.append((url, resp.status_code))
        assert checked > 0
        assert not failures, f"dead catalog URLs: {failures}"
