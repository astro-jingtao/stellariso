"""Locating the Claude Agent Skill shipped inside the package."""

from __future__ import annotations

from pathlib import Path

_SKILL_DIRECTORY = (
    Path(__file__).resolve().parent / "skills" / "stellariso" / "skill"
)


def skill_directory() -> Path:
    """Return the directory of the Claude Agent Skill shipped with stellariso.

    The skill teaches coding agents how to use this library. It is
    installed together with the package as ordinary package data and is
    deployed nowhere on its own; deploying it is an explicit user
    choice. Link or copy the returned directory into a skills directory
    (for example ``~/.claude/skills/stellariso``) — the shipped
    deployment guide, ``skills/SKILL-DEPLOY.md`` inside the
    installation, describes the procedure and its upgrade semantics.
    """
    if not _SKILL_DIRECTORY.is_dir():
        raise FileNotFoundError(
            f"the shipped skill directory is missing: {_SKILL_DIRECTORY}; "
            "the stellariso installation is incomplete (built without the "
            "skills package data)"
        )
    return _SKILL_DIRECTORY
