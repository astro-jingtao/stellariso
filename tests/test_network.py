"""Online smoke tests for the MIST acquisition pipeline.

These talk to the live mist.science interp form; run them explicitly with

    pytest -m network tests/test_network.py

They are excluded from the default suite so upstream outages never break
offline development or CI.
"""

from __future__ import annotations

import pytest

from stellariso.exceptions import SourceUnavailableError
from stellariso.models.mist.backend import read_mist
from stellariso.models.mist.fetch import fetch_mist_subset

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def fetched(tmp_path_factory):
    path, prov = fetch_mist_subset(
        feh=-1.00,
        log_ages=[9.0],
        vvcrit=0.4,
        cache_dir=tmp_path_factory.mktemp("mist_net"),
    )
    return path, prov


def test_form_roundtrip_produces_readable_file(fetched):
    path, prov = fetched
    assert path.exists() and path.stat().st_size > 100_000
    s = read_mist(path, provenance=prov)
    assert s.identity.family == "mist"
    assert s.identity.release == "1.2"
    assert s.keys() == [9.0]
    iso = s[0]
    assert iso.selection["initial_feh"] == -1.00
    assert iso.native.metadata["zinit"] == pytest.approx(1.88066e-03, rel=1e-3)


def test_provenance_records_official_source(fetched):
    _, prov = fetched
    src = prov.data_sources[0]
    assert src.url == "https://mist.science/iso_form.php"
    assert prov.assets[0].checksum  # sha256 recorded
    assert prov.assets[0].size_bytes > 0


def test_second_call_uses_cache(fetched, tmp_path, capsys):
    path1, _ = fetched
    path2, _ = fetch_mist_subset(
        feh=-1.00, log_ages=[9.0], vvcrit=0.4, cache_dir=path1.parent
    )
    assert path1 == path2
