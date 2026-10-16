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
  sampling, axis or fixed-field values, or a record whose complete form
  can no longer be reconstructed); the data stays on disk, marked, and
  the whole cell is fetched anew — never patched with a complementary grid;
- ``pending`` — nothing archived for the cell yet.

The full design spans every effective axis combination (tens of
thousands of cells); the report's status counts and listings cover the
current fetch stage's committed target, and beyond-target designed
cells appear as summary counts only. Products outside the design
(historical option-variation tables, or payloads that map nowhere) are
``superseded``. Every classification carries its reasons, so the
generated report is the review artifact for re-fetch and deletion
decisions, which stay human.

``tools/parsec/blueprint_status.py`` is the CLI face of this module.
"""

from __future__ import annotations

import gzip
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from stellariso.models.parsec import blueprint as bp
from stellariso.models.parsec.cmd_form import DEFAULT_FIELDS

__all__ = [
    "PartScan",
    "CellScan",
    "DatabaseReport",
    "scan_database",
]

#: Fields every archived payload must carry for the request to be
#: replayable as-is (DEFAULT_FIELDS already includes the submit button;
#: an unchecked ``output_gzip`` is legitimately absent on the wire).
_REQUIRED_FIELDS = frozenset(DEFAULT_FIELDS)
_OPTIONAL_FIELDS = frozenset({"output_gzip"})


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
    return bp.expected_payload(cell, which)


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
                    bp.payload_diff(self.payload, _expected_payload(cell, self.which))
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
    """The cells the current fetch stage commits to fetching."""
    return bp.fetch_cells(ts)


@lru_cache(maxsize=None)
def _designed_cells(set_key: str) -> tuple[bp.Cell, ...]:
    """The full designed cell list of one set (deterministic, cached)."""
    return bp.cells(bp.TRACK_SETS[set_key])


@lru_cache(maxsize=None)
def _cell_index(set_key: str) -> dict[tuple, bp.Cell]:
    """Axis tuple -> designed cell, for one set (built once per set)."""
    return {
        (c.mh, c.omega, c.eta, c.n_intpc, c.dust_m, c.dust_c, c.lpv): c
        for c in _designed_cells(set_key)
    }


def _find_cell(
    ts: bp.TrackSet,
    mh: float,
    omega: float,
    eta: float,
    n_intpc: int,
    dust_m: str,
    dust_c: str,
    lpv: str,
) -> bp.Cell | None:
    return _cell_index(ts.key).get((mh, omega, eta, n_intpc, dust_m, dust_c, lpv))


def _cell_of_payload(payload: dict[str, str]) -> bp.Cell | None:
    tracks = (payload.get("track_parsec"), payload.get("track_colibri"))
    key = next((k for k, ts in bp.TRACK_SETS.items()
                if (ts.track_parsec, ts.track_colibri) == tracks), None)
    if key is None:
        return None
    try:
        mh = float(payload["isoc_metlow"])
        omega = float(payload["track_omegai"])
        eta = float(payload["eta_reimers"])
        n_intpc = int(payload["n_inTPC"])
        dust_m = payload["dust_sourceM"]
        dust_c = payload["dust_sourceC"]
        lpv = payload["kind_LPV"]
    except (KeyError, ValueError):
        return None
    return _find_cell(bp.TRACK_SETS[key], mh, omega, eta, n_intpc, dust_m, dust_c, lpv)


def _cell_of_label(set_key: str, label: str) -> bp.Cell | None:
    """The cell a directory name encodes (fallback when no record)."""
    ts = bp.TRACK_SETS[set_key]
    text = label
    if ts.label_prefix:
        if not text.startswith(ts.label_prefix):
            return None
        text = text[len(ts.label_prefix) :]

    # strip the optional axis suffixes (fixed emitted order, but parsed
    # tolerantly from the end); dust names carry no underscores.
    eta: float | None = None
    omega: float | None = None
    n_intpc: int | None = None
    dust_m: str | None = None
    dust_c: str | None = None
    lpv: str | None = None
    while True:
        if lpv is None and text.endswith(tuple(f"_lpv{v}" for v in bp.LPV_VALUES)):
            lpv = text.rsplit("_lpv", 1)[1]
            text = text.rsplit("_lpv", 1)[0]
        elif dust_c is None and text.endswith(tuple(f"_dC{v}" for v in bp.DUST_C_VALUES)):
            dust_c = text.rsplit("_dC", 1)[1]
            text = text.rsplit("_dC", 1)[0]
        elif dust_m is None and text.endswith(tuple(f"_dM{v}" for v in bp.DUST_M_VALUES)):
            dust_m = text.rsplit("_dM", 1)[1]
            text = text.rsplit("_dM", 1)[0]
        elif n_intpc is None and text.endswith(tuple(f"_n{v}" for v in bp.N_INTPC_VALUES)):
            n_intpc = int(text.rsplit("_n", 1)[1])
            text = text.rsplit("_n", 1)[0]
        elif eta is None and (sep := text.rfind("_e")) != -1 and "." in text[sep + 2 :]:
            try:
                eta = float(text[sep + 2 :])
            except ValueError:
                break
            text = text[:sep]
        elif omega is None and (sep := text.rfind("_w")) != -1 and "." in text[sep + 2 :]:
            try:
                omega = float(text[sep + 2 :])
            except ValueError:
                break
            text = text[:sep]
        else:
            break

    if not text.startswith("mh_") or len(text) < 5 or text[3] not in "mp":
        return None
    try:
        mh = (1.0 if text[3] == "p" else -1.0) * float(text[4:])
    except ValueError:
        return None
    eta = bp.CANONICAL_ETA if eta is None else eta
    omega = 0.0 if omega is None else omega
    n_intpc = bp.CANONICAL_N_INTPC if n_intpc is None else n_intpc
    dust_m = bp.CANONICAL_DUST_M if dust_m is None else dust_m
    dust_c = bp.CANONICAL_DUST_C if dust_c is None else dust_c
    lpv = bp.CANONICAL_LPV if lpv is None else lpv
    return _find_cell(ts, mh, omega, eta, n_intpc, dust_m, dust_c, lpv)


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
        """Status counts over the cells the fetch stage commits to."""
        out = {"complete": 0, "log_only": 0, "refetch": 0, "pending": 0}
        target = {c.label for c in _target_cells(bp.TRACK_SETS[set_key])}
        for scan in self.cells[set_key].values():
            if scan.cell.label in target:
                out[scan.status] += 1
        return out

    def tier_totals(self) -> dict[str, dict[str, int]]:
        totals: dict[str, dict[str, int]] = {}
        for key, ts in bp.TRACK_SETS.items():
            bucket = totals.setdefault(
                ts.tier,
                {"target": 0, "complete": 0, "log_only": 0, "refetch": 0, "pending": 0},
            )
            bucket["target"] += len(_target_cells(ts))
            for status, n in self.counts(key).items():
                bucket[status] += n
        return totals

    def jobs_to_target(self) -> dict[str, int]:
        """Submissions still needed to reach the fetch-stage target."""
        jobs = {"primary": 0, "secondary": 0}
        for key, ts in bp.TRACK_SETS.items():
            target = {c.label for c in _target_cells(ts)}
            for scan in self.cells[key].values():
                if scan.cell.label not in target:
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
        key: {cell.label: CellScan(cell=cell) for cell in _designed_cells(key)}
        for key in bp.TRACK_SETS
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


def _eta_line(ts: bp.TrackSet) -> str:
    if not ts.eta_applies:
        return (
            f"Reimers eta: fixed {bp.CANONICAL_ETA:g} (v2.0 integrates no Reimers "
            "RGB mass loss; its header echo carries no eta line)"
        )
    return (
        f"Reimers eta: 0.0 to 0.5, step 0.1 -> {len(bp.ETA_VALUES)} values "
        f"(current fetch stage: {', '.join(f'{v:g}' for v in bp.FETCH_ETA_VALUES)})"
    )


def _nintpc_line(ts: bp.TrackSet) -> str:
    if not ts.nintpc_applies:
        return (
            f"TP-cycle resolution n_inTPC: fixed {bp.CANONICAL_N_INTPC} "
            "(no COLIBRI section in this set's output)"
        )
    values = ", ".join(str(v) for v in bp.N_INTPC_VALUES)
    return (
        f"TP-cycle resolution n_inTPC: {values} -> {len(bp.N_INTPC_VALUES)} values "
        f"(canonical {bp.CANONICAL_N_INTPC} at the fetch stage; same tracks, "
        "different pulse-cycle phase sampling)"
    )


def _dust_line(ts: bp.TrackSet) -> str:
    if not ts.dust_applies:
        return (
            f"Circumstellar dust: canonical {bp.CANONICAL_DUST_M}/{bp.CANONICAL_DUST_C} "
            "only (no TP-AGB section in this set's 17-column output; the header "
            "echo lines are boilerplate)"
        )
    return (
        f"Circumstellar dust: {len(bp.DUST_M_VALUES)} O-rich x {len(bp.DUST_C_VALUES)} "
        f"C-rich = {len(bp.DUST_M_VALUES) * len(bp.DUST_C_VALUES)} combinations "
        f"(canonical {bp.CANONICAL_DUST_M}/{bp.CANONICAL_DUST_C} at the fetch stage)"
    )


def _lpv_line(ts: bp.TrackSet) -> str:
    if not ts.lpv_applies:
        return (
            f"LPV prescription: canonical {bp.CANONICAL_LPV} only "
            "(no period columns in this set's output)"
        )
    return (
        f"LPV prescription: {', '.join(bp.LPV_VALUES)} -> {len(bp.LPV_VALUES)} values "
        f"(canonical {bp.CANONICAL_LPV} at the fetch stage; option 1 changes "
        "the column set itself)"
    )


def render_markdown(report: DatabaseReport) -> str:
    """The full review artifact: declarations, statuses, reasons, lists."""
    lines: list[str] = []
    lines.append("# PARSEC blueprint status")
    lines.append("")
    lines.append(f"Database: `{report.database}`")
    lines.append(f"Generated: {report.generated_at} (UTC)")
    designed_total = sum(len(c) for c in report.cells.values())
    target_total = sum(len(_target_cells(ts)) for ts in bp.TRACK_SETS.values())
    lines.append(
        f"Blueprint: {designed_total} designed cells (full axis coverage), "
        f"{target_total} in the current fetch stage's target, "
        "2 age-grid submissions per cell (see docs/parsec/blueprint.md)"
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
        lines.append(_eta_line(ts))
        lines.append(_nintpc_line(ts))
        lines.append(_dust_line(ts))
        lines.append(_lpv_line(ts))
        lines.append(
            "Ages per cell: log10(age/yr) 6.6 to 10.13 dex, step 0.02 dex -> "
            f"{bp.expected_log_ages()} isochrones (output.dat); linear "
            f"{bp.LINEAR_AGE_GRID[0]} to {bp.LINEAR_AGE_GRID[1]} yr, "
            f"step {bp.LINEAR_AGE_GRID[2]} yr -> {bp.expected_linear_ages()} "
            "isochrones (output_linear.dat)"
        )
        eta_stage = ", ".join(f"{v:g}" for v in bp.FETCH_ETA_VALUES)
        if ts.tier == "secondary":
            target_note = (
                " (sparse slice: anchors "
                + ", ".join(f"{v:+g}" for v in bp.SPARSE_ANCHOR_MH)
                + " + window edges; eta " + eta_stage + ", canonical dust/LPV)"
            )
        else:
            target_note = " (full [M/H] extent; eta " + eta_stage + ", canonical dust/LPV)"
        lines.append(
            f"Designed cells: {len(per_cell)}; fetch-stage target: {len(target)}{target_note}"
        )
        lines.append(
            "Status over the fetch-stage target: "
            + ", ".join(f"{status} {counts[status]}" for status in ("complete", "log_only", "refetch", "pending"))
        )
        lines.append("")
        by_status: dict[str, list[CellScan]] = {"complete": [], "log_only": [], "refetch": [], "pending": []}
        target_keys = {c.label for c in target}
        beyond_pending = 0
        for scan in per_cell.values():
            if scan.cell.label not in target_keys:
                if scan.status == "pending":
                    beyond_pending += 1
                continue
            by_status[scan.status].append(scan)
        for status, label in (
            ("refetch", "Re-fetch (archived data kept on disk, marked)"),
            ("complete", "Complete"),
            ("log_only", "Log grid only (linear refinement pending)"),
            ("pending", "Pending within the fetch-stage target"),
        ):
            scans = sorted(by_status[status], key=lambda s: s.cell.label)
            if not scans:
                continue
            lines.append(f"### {label} — {len(scans)}")
            for scan in scans:
                if status == "refetch":
                    lines.append(
                        f"- {scan.cell.label} — "
                        f"{'; '.join(scan.reasons) or 'unspecified non-conformance'}"
                    )
                else:
                    lines.append(f"- {scan.cell.label}")
            lines.append("")
        if beyond_pending:
            lines.append(
                f"Beyond the fetch-stage target: {beyond_pending} designed cells of "
                "this set are pending (later axis-value stages; same layout, no redesign)."
            )
            lines.append("")
    lines.append("## Totals")
    lines.append("")
    totals = report.tier_totals()
    jobs = report.jobs_to_target()
    for tier in ("primary", "secondary"):
        t = totals[tier]
        lines.append(
            f"- {tier}: {t['target']} fetch-target cells — complete {t['complete']}, "
            f"log-only {t['log_only']}, re-fetch {t['refetch']}, pending {t['pending']}; "
            f"{jobs[tier]} submissions to target (log-only needs 1, the linear grid; "
            "re-fetch and pending need 2, both grids)"
        )
    designed_cells = sum(len(c) for c in report.cells.values())
    all_refetch = sum(
        1 for per_set in report.cells.values() for s in per_set.values() if s.status == "refetch"
    )
    lines.append(
        f"- full design: {designed_cells} cells ({designed_cells * 2} submissions); "
        f"re-fetch-marked anywhere (in or out of fetch target): {all_refetch}"
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
            + f" over the fetch-stage target"
        )
    totals = report.tier_totals()
    jobs = report.jobs_to_target()
    for tier in ("primary", "secondary"):
        t = totals[tier]
        lines.append(
            f"{tier} total: {t['target']} fetch-target cells, {jobs[tier]} submissions to target"
        )
    lines.append(f"superseded: {len(report.superseded)}; payload gaps: {len(report.payload_gaps)}")
    return "\n".join(lines)
