"""Tests for the Claude Agent Skill shipped inside the package."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import stellariso
from stellariso import skill_directory

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSkillDirectory:
    def test_returns_directory_with_skill_md(self):
        assert (skill_directory() / "SKILL.md").is_file()

    def test_directory_name_matches_frontmatter_name(self):
        # two-layer layout: SKILL.md lives in skill/, whose container
        # (one level up) carries the skill's name; a deployment links
        # skill/ under that name.
        text = (skill_directory() / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---")
        frontmatter = text.split("---")[1]
        assert f"name: {skill_directory().parent.name}" in frontmatter

    def test_ships_inside_the_package_tree(self):
        package_root = Path(stellariso.__file__).resolve().parent
        assert skill_directory().is_relative_to(package_root)

    def test_referenced_files_exist(self):
        # every references/... path named in SKILL.md must exist
        text = (skill_directory() / "SKILL.md").read_text(encoding="utf-8")
        for name in ("point-queries", "two-layers", "database", "parsec-cmd-form"):
            assert (skill_directory() / "references" / f"{name}.md").is_file()
        assert text  # non-empty skill body

    def test_deployment_artifacts_ship_alongside(self):
        skills_root = skill_directory().parent.parent
        assert (skills_root / "SKILL-DEPLOY.md").is_file()
        assert (skill_directory().parent / "meta.yaml").is_file()


class TestWheelContainsSkill:
    def test_wheel_includes_skill_files(self, tmp_path):
        pytest.importorskip("setuptools")
        wheel_dir = tmp_path / "wheel"
        wheel_dir.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "-w",
                str(wheel_dir),
                str(REPO_ROOT),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"wheel build failed:\n{result.stderr}")
        (wheel,) = wheel_dir.glob("stellariso-*.whl")
        with zipfile.ZipFile(wheel) as zf:
            names = set(zf.namelist())
        assert "stellariso/skills/stellariso/skill/SKILL.md" in names
        assert "stellariso/skills/stellariso/skill/CHANGELOG.md" in names
        assert "stellariso/skills/stellariso/skill/references/point-queries.md" in names
        assert "stellariso/skills/stellariso/meta.yaml" in names
        assert "stellariso/skills/SKILL-DEPLOY.md" in names
        assert "stellariso/skill.py" in names
