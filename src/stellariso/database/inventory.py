"""Regeneration of the database-root derived artifacts.

``database.json`` (the machine inventory), ``README.md`` (the human
summary), and the ``unified-parameters.md`` documentation snapshot are
derived state: they are rebuilt from the product directories alone,
never copied between machines and never merged — a receiving machine
regenerates its own with :func:`write_inventory` (exposed as
``stellariso.refresh_database`` together with the status report).
"""

from __future__ import annotations

import json
from pathlib import Path

from stellariso.database.core import Database
from stellariso.database.manifest import utc_now_iso

__all__ = ["write_inventory"]


def write_inventory(root: Path) -> None:
    from stellariso import __version__

    products = Database(root).products
    inventory = {
        "stellariso_version": __version__,
        "generated_at": utc_now_iso(),
        "products": [
            {
                "family": p.family,
                "release": p.release,
                "label": p.label,
                "kind": p.kind,
                "url": p.url,
                "sha256": p.sha256,
                "size_bytes": p._primary_entry().get("size_bytes"),
            }
            for p in products
        ],
    }
    tmp = root / "database.json.tmp"
    tmp.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(root / "database.json")

    lines = [
        "# stellariso isochrone database",
        "",
        f"Built by stellariso {__version__} on {inventory['generated_at']}.",
        "",
        "Each `<family>/<release or set>/<label>` directory is one product: "
        "its archived data (the official package archive, or the computed "
        "form tables with their acquisition records), any extracted data "
        "files, and a MANIFEST.json recording the source URL, sha256, size, "
        "retrieval time, file format, and the literature to cite. The "
        "database is self-contained: with the upstream websites gone, the "
        "manifests and the copied mapping documentation below still explain "
        "every file.",
        "",
        "The whole database, or any subset of its product directories, can "
        "be copied to another machine and opened there:",
        "",
        "```python",
        "import stellariso",
        f"db = stellariso.open_database({str(root)!r})",
        "grid = db.grid('mist/1.2', label='vvcrit0.4_full_isos')",
        "```",
        "",
        "## Products",
        "",
        "| Product | Kind | Size (bytes) | Source |",
        "|---|---|---|---|",
    ]
    for p in products:
        size = p._primary_entry().get("size_bytes")
        lines.append(
            f"| `{p.family}/{p.release}/{p.label}` | {p.kind} "
            f"| {size if size else '—'} | {p.url or 'manual'} |"
        )
    lines += [
        "",
        "## Citations",
        "",
    ]
    seen = set()
    for p in products:
        for citation in p.manifest.get("references", []):
            if citation not in seen:
                seen.add(citation)
                lines.append(f"- {citation}")
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    from stellariso.registry.docs import render_documentation

    (root / "unified-parameters.md").write_text(
        render_documentation(), encoding="utf-8", newline="\n"
    )
