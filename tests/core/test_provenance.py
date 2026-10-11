"""Tests for the provenance schema and its serialization."""

from __future__ import annotations

import json

from stellariso.provenance import (
    DataAsset,
    Provenance,
    Reference,
    SourceChain,
    SourceClass,
    SourceRecord,
    SourceStatus,
)


def _record(source_class=SourceClass.OFFICIAL_ORIGIN, **kw):
    return SourceRecord(
        source_class=source_class,
        url=kw.pop("url", "https://mist.science/iso_form.php"),
        accessed_at=kw.pop("accessed_at", "2026-10-11T08:00:00Z"),
        **kw,
    )


class TestSourceRecord:
    def test_defaults(self):
        rec = SourceRecord(source_class=SourceClass.SCIENTIFIC_ARCHIVE)
        assert rec.status is SourceStatus.NOT_CHECKED
        assert rec.url is None

    def test_roundtrip(self):
        rec = _record(status=SourceStatus.VERIFIED)
        d = rec.to_dict()
        assert d["source_class"] == "official_origin"
        assert d["status"] == "verified"
        assert SourceRecord.from_dict(d) == rec

    def test_rejects_bad_class(self):
        import pytest

        with pytest.raises(TypeError):
            SourceRecord(source_class="official_origin")


class TestDataAsset:
    def test_roundtrip_with_source(self):
        asset = DataAsset(
            filename="MIST_v1.2_feh_p0.00_vvcrit0.4.iso",
            size_bytes=7471550,
            checksum_algorithm="sha256",
            checksum="e5c8" * 16,
            retrieved_at="2026-10-11T08:30:00Z",
            source=_record(),
        )
        d = asset.to_dict()
        assert d["source"]["source_class"] == "official_origin"
        again = DataAsset.from_dict(d)
        assert again == asset
        assert again.source.status is SourceStatus.NOT_CHECKED


class TestSourceChain:
    def test_chain_of_custody(self):
        chain = SourceChain(
            upstream_sources=(
                _record(source_class=SourceClass.HISTORICAL_MIRROR),
                _record(source_class=SourceClass.THIRD_PARTY_PACKAGE),
            ),
            immediate_source=_record(source_class=SourceClass.THIRD_PARTY_PACKAGE),
            transformations=("extracted from package data dir",),
        )
        d = chain.to_dict()
        again = SourceChain.from_dict(d)
        assert again == chain
        assert len(again.upstream_sources) == 2


class TestProvenance:
    def test_full_bundle_json_roundtrip(self):
        prov = Provenance(
            data_sources=(_record(),),
            assets=(
                DataAsset(
                    filename="a.iso",
                    checksum="ab" * 32,
                    source=_record(status=SourceStatus.RETRIEVED),
                ),
            ),
            source_chains=(
                SourceChain(
                    immediate_source=_record(),
                    transformations=("gzip -9 of the raw .iso payload",),
                ),
            ),
            scientific_references=(
                Reference(
                    citation="Choi, J., et al. 2016, ApJ, 823, 102",
                    bibcode="2016ApJ...823..102C",
                ),
            ),
            software_references=(
                Reference(citation="MESA r7503 via MIST isochrone service"),
            ),
            transformations=("parsed by stellariso.mist.reader",),
        )
        text = json.dumps(prov.to_dict())
        again = Provenance.from_dict(json.loads(text))
        assert again == prov
        # separation of concerns: citations are not data sources
        assert again.scientific_references[0].citation.startswith("Choi")
        assert again.data_sources[0].source_class is SourceClass.OFFICIAL_ORIGIN
