"""Measure a database against the PARSEC acquisition blueprint.

The scanner is pure local I/O: it reads the product directories a
database actually holds (``parsec/<set>/<label>/``), reconstructs each
product's blueprint cell from the archived acquisition record (the
authoritative source — the payload, not the directory name), and
classifies every designed cell:

- ``complete`` — both age grids archived with blueprint-conforming
  payloads and the expected isochrone counts;
- ``log_only`` — the log-age half conforms, the linear-age refinement
  is still to be fetched into the same directory;
- ``refetch`` — an archived table does not match the design (age
  sampling, fixed-field values, or a record whose complete form can no
  longer be reconstructed); the data stays on disk, marked, and the
  whole cell is fetched anew — never patched with a complementary grid;
- ``pending`` — nothing archived for the cell yet.

Products outside the design (historical option-variation tables, or
payloads that map nowhere) are ``superseded``. Every classification
carries its reasons, so the generated report is the review artifact for
re-fetch and deletion decisions, which stay human.

``tools/blueprint_status.py`` is the CLI face of this module.
"""

from __future__ import annotations

import gzip
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stellariso.models.parsec import blueprint as bp
from stellariso.models.parsec.cmd_form import DEFAULT_FIELDS, CmdFieldSet

__all__ = [
    "PartScan",
    "CellScan",
    "DatabaseReport",
    "scan_database",
]

#: (track_parsec, track_colibri) of a payload -> blueprint set key.
_SET_BY_TRACKS = {
    (ts.track_parsec, ts.track_colibri): key for key, ts in bp.TRACK_SETS.items()
}

#: Fields every archived payload must carry for the request to be
#: replayable as-is (DEFAULT_FIELDS already includes the submit button;
#: an unchecked ``output_gzip`` is legitimately absent on the wire).
_REQUIRED_FIELDS = frozenset(DEFAULT_FIELDS)
_OPTIONAL_FIELDS = frozenset({"output_gzip"})

_AGE_FIELDS = frozenset(
    (
        "isoc_isagelog",
        "isoc_agelow",
        "isoc_ageupp",
        "isoc_dage",
        "isoc_lagelow",
        "isoc_lageupp",
        "isoc_dlage",
        "isoc_ismetlog",
        "isoc_metlow",
        "isoc_metupp",
        "isoc_dmet",
    )
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def count_blocks(path: Path) -> int | None:
    """Isochrone blocks in an archived table (its repeated column line).

    ``None`` when the file is missing or unreadable. Gzip is detected by
    content: the server force-gzips large outputs under the same name.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    stream = io.BytesIO(gzip.decompress(raw)) if raw[:2] == b"\x1f\x8b" else io.BytesIO(raw)
    n = 0
    for line in stream:
        stripped = line.lstrip()
        if stripped.startswith(b"#") and b"Zini" in stripped:
            n += 1
    return n


def _expected_payload(cell: bp.Cell, which: str) -> dict[str, str]:
    fields = cell.log_fields() if which == "log" else cell.linear_fields()
    return CmdFieldSet.from_overrides(**fields).as_dict()


def _same_value(name: str, actual: str, expected: str) -> bool:
    if name in _AGE_FIELDS:
        try:
            return abs(float(actual) - float(expected)) < 1e-9
        except ValueError:
            return False
    return actual == expected


def _payload_diff(actual: dict[str, str], expected: dict[str, str]) -> list[str]:
    """Field-level differences of an archived payload against the design."""
    diff: list[str] = []
    for name in sorted(set(expected) - set(actual)):
        diff.append(f"missing field {name}")
    for name in sorted(set(actual) - set(expected) - _OPTIONAL_FIELDS):
        diff.append(f"unexpected field {name}")
    for name in sorted(set(actual) & set(expected)):
        if not _same_value(name, actual[name], expected[name]):
            diff.append(f"{name}: archived {actual[name]!r} != designed {expected[name]!r}")
    return diff


@dataclass
class PartScan:
    """One archived submission (one age grid of one cell directory)."""

    which: str  # "log" | "linear"
    directory: Path
    label: str
    payload: dict[str, str] = field(default_factory=dict)
    blocks: int | None = None
    conforms: bool = False
    reasons: list[str] = field(default_factory=list)

    def scan(self, cell: bp.Cell) -> None:
        table = "output.dat" if self.which == "log" else "output_linear.dat"
        record_path = self.directory / (table + ".record.json")
        if not record_path.exists():
            self.reasons.append(f"no acquisition record ({record_path.name})")
        else:
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.reasons.append(f"unreadable acquisition record: {exc}")
            else:
                self.payload = record.get("request_fields", {})
                self.reasons.extend(
                    _payload_diff(self.payload, _expected_payload(cell, self.which))
                )
        self.blocks = count_blocks(self.directory / table)
        expected_blocks = (
            bp.expected_log_ages() if self.which == "log" else bp.expected_linear_ages()
        )
        if self.blocks is None:
            self.reasons.append(f"{self.which}-age table missing or unreadable")
        elif self.blocks != expected_blocks:
            self.reasons.append(
                f"{self.which}-age table has {self.blocks} isochrones, "
                f"design expects {expected_blocks}"
            )
        self.conforms = not self.reasons


@dataclass
class CellScan:
    """The blueprint verdict for one cell of one database."""

    cell: bp.Cell
    parts: dict[str, PartScan | None] = field(default_factory=dict)
    status: str = "pending"
    reasons: list[str] = field(default_factory=list)

    def decide(self) -> None:
        archived = {w: p for w, p in self.parts.items() if p is not None}
        if not archived:
            self.status = "pending"
            return
        self.reasons = [r for p in archived.values() for r in p.reasons]
        if any(not p.conforms for p in archived.values()):
            # A non-conforming archived table voids the cell: fetch it
            # anew (both grids), never a complementary patch.
            self.status = "refetch"
        elif set(archived) == {"log"}:
            self.status = "log_only"
        else:
            self.status = "complete"


def _target_cells(ts: bp.TrackSet) -> tuple[bp.Cell, ...]:
    """The cells a set's tier commits to fetching."""
    return bp.cells(ts) if ts.tier == "primary" else bp.cells(ts, sparse=True)


def _find_cell(ts: bp.TrackSet, mh: float, omega: float) -> bp.Cell | None:
    for cell in bp.cells(ts):
        if abs(cell.mh - mh) < 1e-6 and abs(cell.omega - omega) < 1e-6:
            return cell
    return None


def _cell_of_payload(payload: dict[str, str]) -> bp.Cell | None:
    key = _SET_BY_TRACKS.get((payload.get("track_parsec"), payload.get("track_colibri")))
    if key is None:
        return None
    try:
        mh = float(payload["isoc_metlow"])
        omega = float(payload["track_omegai"])
    except (KeyError, ValueError):
        return None
    return _find_cell(bp.TRACK_SETS[key], mh, omega)


def _cell_of_label(set_key: str, label: str) -> bp.Cell | None:
    """The cell a directory name encodes (fallback when no record)."""
    ts = bp.TRACK_SETS[set_key]
    text = label
    if ts.label_prefix:
        if not text.startswith(ts.label_prefix):
            return None
        text = text[len(ts.label_prefix) :]
    omega = 0.0
    if "_w" in text:
        text, _, omega_text = text.rpartition("_w")
        try:
            omega = float(omega_text)
        except ValueError:
            return None
    if not text.startswith("mh_") or len(text) < 5 or text[3] not in "mp":
        return None
    try:
        mh = (1.0 if text[3] == "p" else -1.0) * float(text[4:])
    except ValueError:
        return None
    return _find_cell(ts, mh, omega)


def _load_any_payload(directory: Path) -> dict[str, str]:
    for name in ("output.dat.record.json", "output_linear.dat.record.json"):
        path = directory / name
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("request_fields", {})
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


@dataclass
class DatabaseReport:
    """The full measurement of one database against the blueprint."""

    database: Path
    generated_at: str
    cells: dict[str, dict[str, CellScan]] = field(default_factory=dict)
    superseded: list[dict] = field(default_factory=list)
    payload_gaps: list[str] = field(default_factory=list)

    def counts(self, set_key: str) -> dict[str, int]:
        """Status counts over the cells the set's tier commits to."""
        out = {"complete": 0, "log_only": 0, "refetch": 0, "pending": 0}
        target = {(c.mh, c.omega) for c in _target_cells(bp.TRACK_SETS[set_key])}
        for scan in self.cells[set_key].values():
            if (scan.cell.mh, scan.cell.omega) in target:
                out[scan.status] += 1
        return out

    def tier_totals(self) -> dict[str, dict[str, int]]:
        totals: dict[str, dict[str, int]] = {}
        for key, ts in bp.TRACK_SETS.items():
            bucket = totals.setdefault(
                ts.tier,
                {"designed": 0, "complete": 0, "log_only": 0, "refetch": 0, "pending": 0},
            )
            bucket["designed"] += len(_target_cells(ts))
            for status, n in self.counts(key).items():
                bucket[status] += n
        return totals

    def jobs_to_target(self) -> dict[str, int]:
        """Submissions still needed to reach each tier's fetch target."""
        jobs = {"primary": 0, "secondary": 0}
        for key, ts in bp.TRACK_SETS.items():
            target = {(c.mh, c.omega) for c in _target_cells(ts)}
            for scan in self.cells[key].values():
                if (scan.cell.mh, scan.cell.omega) not in target:
                    continue
                if scan.status == "log_only":
                    jobs[ts.tier] += 1
                elif scan.status in ("refetch", "pending"):
                    jobs[ts.tier] += 2
        return jobs


def scan_database(database: Path | str) -> DatabaseReport:
    """Scan ``<database>/parsec`` and classify every blueprint cell."""
    database = Path(database)
    report = DatabaseReport(database=database, generated_at=_now_iso())
    report.cells = {
        key: {cell.label: CellScan(cell=cell) for cell in bp.cells(ts)}
        for key, ts in bp.TRACK_SETS.items()
    }

    parsec_root = database / "parsec"
    product_dirs = (
        sorted(p for p in parsec_root.glob("*/*") if p.is_dir()) if parsec_root.exists() else []
    )

    def _superseded(directory: Path, reason: str) -> None:
        report.superseded.append(
            {"directory": directory.relative_to(database).as_posix(), "reason": reason}
        )

    for directory in product_dirs:
        label = directory.name
        set_key = directory.parent.name
        if set_key not in bp.TRACK_SETS:
            _superseded(directory, "directory outside the blueprint sets")
            continue
        payload = _load_any_payload(directory)
        if payload and not (_REQUIRED_FIELDS <= (set(payload) | _OPTIONAL_FIELDS)):
            report.payload_gaps.append(directory.relative_to(database).as_posix())
        if label.startswith("aux_"):
            _superseded(directory, "option-variation table outside the uniform design")
            continue

        cell = _cell_of_payload(payload) if payload else None
        labeled = _cell_of_label(set_key, label)
        if cell is None:
            cell = labeled
        elif labeled is not None and labeled.label != cell.label:
            _superseded(
                directory,
                f"payload says cell {cell.label} but directory name says {labeled.label}",
            )
            continue
        if cell is None:
            _superseded(directory, "maps to no designed cell")
            continue
        scan = report.cells[cell.set.key].get(cell.label)
        if scan is None or scan.parts.get("log") is not None:
            _superseded(directory, f"duplicate or misplaced directory for cell {cell.label}")
            continue

        part = PartScan(which="log", directory=directory, label=label)
        part.scan(cell)
        scan.parts["log"] = part
        if (directory / "output_linear.dat.record.json").exists():
            linear = PartScan(which="linear", directory=directory, label=label)
            linear.scan(cell)
            scan.parts["linear"] = linear

    for per_set in report.cells.values():
        for scan in per_set.values():
            scan.decide()
    return report


def _omega_line(ts: bp.TrackSet) -> str:
    if not ts.rotates:
        return "Initial rotation omega_i: 0 (fixed; the form offers rotation for v2.0 only)"
    values = ", ".join(f"{w:g}" for w in ts.omega_values)
    return (
        f"Initial rotation omega_i: {values} -> {len(ts.omega_values)} values "
        "(0 to 0.9 step 0.1, plus 0.99)"
    )


def render_markdown(report: DatabaseReport) -> str:
    """The full review artifact: declarations, statuses, reasons, lists."""
    lines: list[str] = []
    lines.append("# PARSEC blueprint status")
    lines.append("")
    lines.append(f"Database: `{report.database}`")
    lines.append(f"Generated: {report.generated_at} (UTC)")
    designed_total = sum(len(c) for c in report.cells.values())
    lines.append(
        f"Blueprint: {designed_total} designed cells, 2 age-grid submissions each "
        f"(full design; see docs/parsec-blueprint.md)"
    )
    lines.append("")
    for key, ts in bp.TRACK_SETS.items():
        per_cell = report.cells[key]
        counts = report.counts(key)
        target = _target_cells(ts)
        lines.append(f"## {key} — {ts.tier}")
        lines.append("")
        lines.append(
            f"Tracks: `{ts.track_parsec}` + `track_colibri={ts.track_colibri}`; "
            f"window: {ts.mh_window}"
        )
        supplements = [v for v in ts.mh_values if abs(v / bp.MH_STEP - round(v / bp.MH_STEP)) > 1e-9]
        supp_text = (
            "; boundary supplements: " + ", ".join(f"{v:+g}" for v in supplements) if supplements else ""
        )
        lines.append(
            f"Compositions [M/H]: {ts.mh_low:+g} to {ts.mh_high:+g}, step {bp.MH_STEP:g} dex "
            f"-> {len(ts.mh_values)} values{supp_text}"
        )
        lines.append(_omega_line(ts))
        lines.append(
            "Ages per cell: log10(age/yr) 6.6 to 10.13 dex, step 0.02 dex -> "
            f"{bp.expected_log_ages()} isochrones (output.dat); linear 0.0 to 4.0e6 yr, "
            f"step 1.0e5 yr -> {bp.expected_linear_ages()} isochrones (output_linear.dat)"
        )
        if ts.tier == "primary":
            lines.append(f"Tier target: full extent, {len(target)} cells")
        else:
            lines.append(
                f"Tier target: sparse slice, {len(target)} of {len(per_cell)} designed cells "
                f"(anchors {', '.join(f'{v:+g}' for v in bp.SPARSE_ANCHOR_MH)} + window edges)"
            )
        lines.append(
            "Status over the tier target: "
            + ", ".join(f"{status} {counts[status]}" for status in ("complete", "log_only", "refetch", "pending"))
        )
        lines.append("")
        by_status: dict[str, list[CellScan]] = {"complete": [], "log_only": [], "refetch": [], "pending": []}
        for scan in per_cell.values():
            by_status[scan.status].append(scan)
        for status, label in (
            ("refetch", "Re-fetch (archived data kept on disk, marked)"),
            ("complete", "Complete"),
            ("log_only", "Log grid only (linear refinement pending)"),
            ("pending", "Pending (nothing archived)"),
        ):
            scans = sorted(by_status[status], key=lambda s: s.cell.label)
            if not scans:
                continue
            lines.append(f"### {label} — {len(scans)}")
            target_keys = {(c.mh, c.omega) for c in target}
            for scan in scans:
                beyond = (
                    ts.tier == "secondary" and (scan.cell.mh, scan.cell.omega) not in target_keys
                )
                suffix = " (beyond tier target)" if beyond else ""
                if status == "refetch":
                    lines.append(
                        f"- {scan.cell.label}{suffix} — "
                        f"{'; '.join(scan.reasons) or 'unspecified non-conformance'}"
                    )
                else:
                    lines.append(f"- {scan.cell.label}{suffix}")
            lines.append("")
    lines.append("## Totals")
    lines.append("")
    totals = report.tier_totals()
    jobs = report.jobs_to_target()
    for tier in ("primary", "secondary"):
        t = totals[tier]
        lines.append(
            f"- {tier}: {t['designed']} tier-target cells — complete {t['complete']}, "
            f"log-only {t['log_only']}, re-fetch {t['refetch']}, pending {t['pending']}; "
            f"{jobs[tier]} submissions to target (log-only needs 1, the linear grid; "
            "re-fetch and pending need 2, both grids)"
        )
    designed_cells = sum(len(c) for c in report.cells.values())
    all_refetch = sum(
        1 for per_set in report.cells.values() for s in per_set.values() if s.status == "refetch"
    )
    lines.append(
        f"- full design: {designed_cells} cells; re-fetch-marked anywhere (in or out of "
        f"tier target): {all_refetch}"
    )
    lines.append("")
    lines.append(f"## Superseded directories — {len(report.superseded)}")
    lines.append("")
    if report.superseded:
        for entry in report.superseded:
            lines.append(f"- `{entry['directory']}` — {entry['reason']}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append(f"## Payload completeness — {len(report.payload_gaps)} gaps")
    lines.append("")
    if report.payload_gaps:
        for rel in report.payload_gaps:
            lines.append(f"- `{rel}`: archived payload misses required fields; treat as re-fetch")
    else:
        lines.append("Every archived acquisition record carries the complete field set.")
    lines.append("")
    lines.append(
        "Marked data is never deleted or refetched by this report; re-fetch and deletion "
        "decisions stay with the database owner."
    )
    return "\n".join(lines) + "\n"


def render_summary(report: DatabaseReport) -> str:
    """The console digest: one line per set plus the tier totals."""
    lines = [f"database: {report.database}"]
    for key, ts in bp.TRACK_SETS.items():
        counts = report.counts(key)
        lines.append(
            f"{key} ({ts.tier}): "
            + ", ".join(f"{s} {counts[s]}" for s in ("complete", "log_only", "refetch", "pending"))
            + f" over the tier target"
        )
    totals = report.tier_totals()
    jobs = report.jobs_to_target()
    for tier in ("primary", "secondary"):
        t = totals[tier]
        lines.append(
            f"{tier} total: {t['designed']} target cells, {jobs[tier]} submissions to target"
        )
    lines.append(f"superseded: {len(report.superseded)}; payload gaps: {len(report.payload_gaps)}")
    return "\n".join(lines)
