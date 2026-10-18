"""Tests for the design vocabulary and the adapter registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from stellariso.database.design import (
    DirectoryMatch,
    FamilyAdapter,
    PartDesign,
    PartVerdict,
    ProductDesign,
    SelectionCriteria,
    adapter_families,
    adapter_for,
)
from stellariso.exceptions import UnsupportedModelError


class _FakeAdapter(FamilyAdapter):
    family = "fake"

    def designs(self):
        return [
            ProductDesign(
                family="fake",
                collection="c1",
                release="r1",
                label="l1",
                kind="thing",
                parts=(PartDesign("archive", "a.txz"),),
                facts={},
            ),
            ProductDesign(
                family="fake",
                collection="c2",
                release="r2",
                label="l2",
                kind="thing",
                parts=(PartDesign("log", "output.dat"), PartDesign("linear", "output_linear.dat")),
                facts={},
            ),
        ]


class TestVocabulary:
    def test_design_paths(self):
        design = _FakeAdapter().designs().__iter__().__next__()
        assert design.key == "c1/l1"
        assert design.relative_dir == "fake/c1/l1"

    def test_part_named_raises_for_unknown(self):
        design = _FakeAdapter().designs().__iter__().__next__()
        with pytest.raises(KeyError, match="no part 'nope'"):
            design.part_named("nope")

    def test_verdict_constructors(self):
        assert PartVerdict.ok("w").kind == "ok"
        assert PartVerdict.ok("w").warnings == ("w",)
        assert PartVerdict.missing().kind == "missing"
        assert PartVerdict.nonconforming("r").reasons == ("r",)

    def test_directory_match(self):
        assert DirectoryMatch().matched is False
        assert DirectoryMatch(superseded_reason="why").superseded_reason == "why"


class TestSelection:
    def test_empty_criteria_matches_everything(self):
        adapter = _FakeAdapter()
        assert all(adapter.matches_criteria(d, SelectionCriteria()) for d in adapter.designs())

    def test_generic_fields(self):
        adapter = _FakeAdapter()
        criteria = SelectionCriteria(collections=("c1",))
        designs = list(adapter.designs())
        assert adapter.matches_criteria(designs[0], criteria) is True
        assert adapter.matches_criteria(designs[1], criteria) is False
        explicit = SelectionCriteria(products=("fake/c2/l2",))
        assert adapter.matches_criteria(designs[1], explicit) is True

    def test_describe(self):
        assert SelectionCriteria().describe() == "everything"
        assert "families" in SelectionCriteria(families=("mist",)).describe()
        assert "target only" in SelectionCriteria(target_only=True).describe()


class TestRegistry:
    def test_builtin_families_registered(self):
        assert adapter_families() == ("mist", "parsec")

    def test_adapter_for_unknown_family(self):
        with pytest.raises(UnsupportedModelError, match="no family adapter"):
            adapter_for("galaxy")

    def test_adapters_are_the_family_subclasses(self):
        from stellariso.models.mist.design import MistAdapter
        from stellariso.models.parsec.design import ParsecAdapter

        assert isinstance(adapter_for("mist"), MistAdapter)
        assert isinstance(adapter_for("parsec"), ParsecAdapter)


class TestMistAdapterClassify:
    """The MIST part verdicts against the real catalog (no network)."""

    @staticmethod
    def _product(db: Path, release="1.2", label="vvcrit0.4_full_isos") -> Path:
        directory = db / "mist" / release / label
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def test_missing_file_is_missing(self, tmp_path: Path):
        from stellariso.models.mist.design import MistAdapter

        adapter = MistAdapter()
        design = next(
            d for d in adapter.designs() if d.label == "vvcrit0.4_full_isos" and d.collection == "1.2"
        )
        directory = self._product(tmp_path)
        verdict = adapter.classify_part(
            design, design.parts[0], directory, {"parts": {}}
        )
        assert verdict.kind == "missing"

    def test_sha_mismatch_is_nonconforming(self, tmp_path: Path):
        from stellariso.models.mist.design import MistAdapter

        adapter = MistAdapter()
        design = next(
            d for d in adapter.designs() if d.label == "vvcrit0.4_full_isos" and d.collection == "1.2"
        )
        directory = self._product(tmp_path)
        (directory / design.parts[0].filename).write_bytes(b"tampered")
        verdict = adapter.classify_part(
            design,
            design.parts[0],
            directory,
            {"parts": {"archive": {"sha256": "0" * 64, "size_bytes": 8}}},
        )
        assert verdict.kind == "nonconforming"
        assert any("sha256" in r for r in verdict.reasons)

    def test_size_deviation_is_ok_with_warning(self, tmp_path: Path):
        from stellariso.integrity import sha256_file
        from stellariso.models.mist.design import MistAdapter

        adapter = MistAdapter()
        design = next(
            d for d in adapter.designs() if d.label == "vvcrit0.4_full_isos" and d.collection == "1.2"
        )
        directory = self._product(tmp_path)
        archive = directory / design.parts[0].filename
        archive.write_bytes(b"payload")
        verdict = adapter.classify_part(
            design,
            design.parts[0],
            directory,
            {"parts": {"archive": {"sha256": sha256_file(archive), "size_bytes": 7}}},
        )
        assert verdict.kind == "ok"  # catalog expects 692,503,712 bytes
        assert verdict.warnings and "bytes" in verdict.warnings[0]

    def test_directory_mapping(self, tmp_path: Path):
        from stellariso.models.mist.design import MistAdapter

        adapter = MistAdapter()
        directory = self._product(tmp_path)
        match = adapter.product_of_directory(tmp_path, directory)
        assert match.matched and match.design.key == "1.2/vvcrit0.4_full_isos"
        unknown = self._product(tmp_path, release="9.9", label="mystery")
        match = adapter.product_of_directory(tmp_path, unknown)
        assert match.matched is False
        assert "release" in match.superseded_reason
