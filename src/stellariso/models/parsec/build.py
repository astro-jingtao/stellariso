"""Build the PARSEC half of a stellariso database from the blueprint.

One blueprint cell becomes one product directory
``parsec/<set-key>/<label>/`` holding BOTH age grids as separate
archived submissions — the log-age table ``output.dat`` and the
linear-age refinement ``output_linear.dat`` — each with its own
acquisition record, described by one extended ``MANIFEST.json``:

- the legacy package/product keys (family, release, label, url, sha256,
  ...) keep describing the log-age table, so inventories and older
  tooling read a cell directory exactly as they read a run-4 product;
- a ``blueprint`` section pins the cell's identity in the design — the
  axis values ([M/H], rotation, Reimers eta, dust mixture, LPV
  prescription), the two designed age grids, and per-part archive
  facts (file, sha256, size, rows, retrieval time, record name).

Acquisition rules, all inherited from the blueprint's declared policy:

- a part whose table is present and checksum-matches its recorded
  sha256 is never re-computed (a form job is server-side compute);
- a cell whose archived log-age half does not conform to the design
  payload is left untouched — no complementary linear table is fetched
  into it (``tools/parsec/blueprint_status.py`` marks such cells for
  review; re-fetching them is a human decision after that review);
- every submission is the complete field set and is archived with its
  exact ordered payload, so the identical request can be replayed.

The module drives only the PARSEC family; ``build_database`` dispatches
to :func:`build_blueprint` for it. Tests inject a fake client; the
network is touched exclusively through
:class:`stellariso.models.parsec.cmd_form.CmdFormClient`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from stellariso.exceptions import SourceUnavailableError
from stellariso.integrity import sha256_file
from stellariso.models.parsec import blueprint as bp
from stellariso.models.parsec.cmd_form import CmdFieldSet
from stellariso.registry import references

__all__ = ["build_cell", "build_blueprint", "fetch_plan"]

#: What each part's table file is named, in submission order.
_PARTS = (("log", "output.dat"), ("linear", "output_linear.dat"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    tmp.replace(path)


def _cell_dir(database: Path, cell: bp.Cell) -> Path:
    return database / "parsec" / cell.set.key / cell.label


def _recorded_sha(manifest: dict, which: str) -> str | None:
    """The sha256 a manifest pins for one part (legacy top-level for log)."""
    part = manifest.get("blueprint", {}).get("parts", {}).get(which)
    if isinstance(part, dict) and part.get("sha256"):
        return part["sha256"]
    if which == "log":
        return manifest.get("sha256")
    return None


def _archived_payload(directory: Path, which: str) -> dict[str, str]:
    record_path = directory / (_table_name(which) + ".record.json")
    try:
        return json.loads(record_path.read_text(encoding="utf-8")).get("request_fields", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _table_name(which: str) -> str:
    return dict(_PARTS)[which]


def _conforms(directory: Path, cell: bp.Cell, which: str) -> bool:
    """Whether the archived part is exactly the designed submission."""
    return not bp.payload_diff(_archived_payload(directory, which),
                               bp.expected_payload(cell, which))


def _verify_header_echo(cell: bp.Cell, comment_lines) -> None:
    expected = cell.set.verify_header
    if expected and not any(expected in ln for ln in comment_lines):
        raise SourceUnavailableError(
            f"parsec/{cell.set.key}/{cell.label}: the server's header echo "
            f"does not contain {expected!r}; echo was {list(comment_lines[:4])}"
        )


def _fetch_part(
    directory: Path,
    cell: bp.Cell,
    which: str,
    client,
    log: Callable[[str], None],
) -> dict:
    """Submit one age grid of the cell and archive table + record.

    Returns the part's ``blueprint.parts`` entry.
    """
    table = _table_name(which)
    fields = CmdFieldSet.from_overrides(
        **(cell.log_fields() if which == "log" else cell.linear_fields())
    )
    log(f"submitting form job for parsec/{cell.set.key}/{cell.label} ({which}-age grid)")
    job = client.submit(fields)
    out = client.fetch_output(job)
    _verify_header_echo(cell, out.comment_lines)
    (directory / table).write_bytes(out.content)
    (directory / (table + ".record.json")).write_text(
        json.dumps(out.record(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "file": table,
        "sha256": out.sha256,
        "size_bytes": len(out.content),
        "n_data_rows": out.n_data_rows,
        "retrieved_at": out.retrieved_at,
        "record": table + ".record.json",
        "url": out.url,
    }


def _write_manifest(directory: Path, cell: bp.Cell, manifest: dict) -> None:
    manifest["blueprint"] = {
        "module": "stellariso.models.parsec.blueprint",
        "set": cell.set.key,
        "track_parsec": cell.set.track_parsec,
        "track_colibri": cell.set.track_colibri,
        "axes": {
            "mh": cell.mh,
            "omega": cell.omega,
            "eta_reimers": cell.eta,
            "n_inTPC": cell.n_intpc,
            "dust_sourceM": cell.dust_m,
            "dust_sourceC": cell.dust_c,
            "kind_LPV": cell.lpv,
        },
        "age_grids": {
            "log": {
                "mode": "log10(age/yr)",
                "low": bp.LOG_AGE_GRID[0],
                "upp": bp.LOG_AGE_GRID[1],
                "step": bp.LOG_AGE_GRID[2],
                "isochrones": bp.expected_log_ages(),
                "file": "output.dat",
            },
            "linear": {
                "mode": "linear (yr)",
                "low": bp.LINEAR_AGE_GRID[0],
                "upp": bp.LINEAR_AGE_GRID[1],
                "step": bp.LINEAR_AGE_GRID[2],
                "isochrones": bp.expected_linear_ages(),
                "file": "output_linear.dat",
            },
        },
        "parts": manifest.get("blueprint", {}).get("parts", {}),
    }
    _atomic_write_json(directory / "MANIFEST.json", manifest)


def _refresh_legacy_keys(manifest: dict, cell: bp.Cell, log_part: dict) -> None:
    """Keep the pre-blueprint MANIFEST keys describing the log table."""
    manifest.update(
        {
            "family": "parsec",
            "release": cell.set.release,
            "label": cell.label,
            "kind": "cmd_form_isochrones",
            "physics": None,
            "url": log_part.get("url"),
            "sha256": log_part.get("sha256"),
            "size_bytes": log_part.get("size_bytes"),
            "expected_size_bytes": None,
            "n_data_files": 1 + (
                1 if manifest.get("blueprint", {}).get("parts", {}).get("linear") else 0
            ),
            "extracted": True,
            "retrieved_at": log_part.get("retrieved_at"),
            "source_class": "official_computed",
            "note": (
                "official CMD web form (https://stev.oapd.inaf.it/cgi-bin/cmd); "
                "one blueprint cell: both age grids in this directory"
            ),
            "format": "cmd_table_3_9",
            "n_data_rows": log_part.get("n_data_rows"),
            "acquisition_record": log_part.get("record"),
            "references": [r.citation for r in references("parsec")],
        }
    )


def build_cell(
    database: Path,
    cell: bp.Cell,
    *,
    client=None,
    pause: float = 5.0,
    log: Callable[[str], None] = print,
) -> str:
    """Acquire one blueprint cell into its directory (both age grids).

    Returns the cell's outcome: ``"kept"`` (already archived and
    checksum-verified, nothing submitted), ``"fetched"`` (at least one
    part computed this call), or ``"mismatch"`` (an archived log-age
    half that is kept verified does not conform to the design — the
    cell is left untouched; see the module docstring for why it is
    never patched).
    """
    directory = _cell_dir(Path(database), cell)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "MANIFEST.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )
    parts = manifest.get("blueprint", {}).get("parts", {})

    # A log-age table that stays in place (present + checksum-matching)
    # must be exactly the designed submission: fetching the linear grid
    # next to a non-conforming log half would build a mixed-grids cell,
    # and overwriting archived data is not this builder's call — the
    # status report marks such cells and their re-fetch stays a human
    # decision.
    log_table = directory / "output.dat"
    if log_table.exists():
        recorded = _recorded_sha(manifest, "log")
        if recorded and sha256_file(log_table) == recorded:
            if not _conforms(directory, cell, "log"):
                log(
                    f"NOTICE parsec/{cell.set.key}/{cell.label}: archived log-age "
                    "table does not match the designed payload; cell left "
                    "untouched (see tools/parsec/blueprint_status.py)"
                )
                return "mismatch"

    fetched = False
    log_part = parts.get("log")

    # A kept log half predating the blueprint section (run-4 products
    # carry a flat top-level sha256) migrates into the parts map, so the
    # extended MANIFEST describes both grids uniformly.
    if log_part is None and manifest.get("sha256") and log_table.exists():
        log_part = {
            "file": "output.dat",
            "sha256": manifest.get("sha256"),
            "size_bytes": manifest.get("size_bytes"),
            "n_data_rows": manifest.get("n_data_rows"),
            "retrieved_at": manifest.get("retrieved_at"),
            "record": manifest.get("acquisition_record") or "output.dat.record.json",
            "url": manifest.get("url"),
        }
        parts["log"] = log_part

    for which, table in _PARTS:
        table_path = directory / table
        if table_path.exists():
            recorded = _recorded_sha(manifest, which)
            if recorded and sha256_file(table_path) == recorded:
                continue  # verified in place; never re-computed
        part = _fetch_part(directory, cell, which, client, log)
        fetched = True
        time.sleep(pause)
        parts[which] = part
        if which == "log":
            log_part = part

    if fetched:
        manifest["blueprint"] = dict(manifest.get("blueprint", {}))
        manifest["blueprint"]["parts"] = parts
        _refresh_legacy_keys(manifest, cell, log_part or {})
        _write_manifest(directory, cell, manifest)
        return "fetched"

    if manifest:
        # nothing fetched, everything verified in place
        manifest["blueprint"] = dict(manifest.get("blueprint", {}))
        manifest["blueprint"]["parts"] = parts
        _write_manifest(directory, cell, manifest)
    log(f"keep verified parsec/{cell.set.key}/{cell.label}")
    return "kept"


def build_blueprint(
    database: Path,
    *,
    client_factory: Callable[[], object] | None = None,
    pause: float = 5.0,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Acquire every cell of the current fetch stage, set by set.

    ``client_factory`` builds one client per run (tests inject fakes;
    the default is the real :class:`CmdFormClient`).
    """
    if client_factory is None:
        from stellariso.models.parsec.cmd_form import CmdFormClient

        client_factory = CmdFormClient
    client = client_factory()
    outcomes = {"kept": 0, "fetched": 0, "mismatch": 0}
    for ts in bp.TRACK_SETS.values():
        for cell in bp.fetch_cells(ts):
            outcomes[build_cell(database, cell, client=client, pause=pause, log=log)] += 1
    return outcomes


def fetch_plan(database: Path | str | None = None) -> dict:
    """What ``build_blueprint`` would acquire, without touching anything.

    With an existing database the plan is measured against it (via the
    status scanner); without one every fetch-stage cell counts as
    pending. Pure local I/O — the dry-run face of the builder.
    """
    from stellariso.models.parsec.blueprint_status import scan_database

    plan = {
        "sets": {
            key: {
                "tier": ts.tier,
                "target_cells": len(bp.fetch_cells(ts)),
                "designed_cells": len(bp.cells(ts)),
            }
            for key, ts in bp.TRACK_SETS.items()
        },
    }
    target_total = sum(v["target_cells"] for v in plan["sets"].values())
    plan["target_cells"] = target_total
    if database is not None and (Path(database) / "parsec").is_dir():
        report = scan_database(database)
        jobs = report.jobs_to_target()
        plan["submissions_to_target"] = jobs["primary"] + jobs["secondary"]
        plan["tier_jobs"] = jobs
    else:
        plan["submissions_to_target"] = 2 * target_total
        plan["tier_jobs"] = {
            tier: 2 * sum(
                len(bp.fetch_cells(ts))
                for ts in bp.TRACK_SETS.values()
                if ts.tier == tier
            )
            for tier in ("primary", "secondary")
        }
    return plan
