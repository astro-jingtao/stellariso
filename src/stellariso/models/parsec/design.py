"""The PARSEC family adapter: the blueprint seen through the generic
database machinery.

The design data itself lives in
:mod:`stellariso.models.parsec.blueprint` (track sets, axes, cells, age
grids, expected payloads) and the request layer in
:mod:`stellariso.models.parsec.cmd_form`; this module only adapts them
to the :class:`~stellariso.database.design.FamilyAdapter` contract:

- every designed cell is a product ``parsec/<set-key>/<label>/`` whose
  two parts are the log-age table (``output.dat``) and the linear-age
  refinement (``output_linear.dat``);
- a directory maps into the design by its archived acquisition record
  (the payload is authoritative, not the directory name), with the
  name as fallback when no record survived;
- a part conforms when its archived payload is exactly the designed
  submission and its isochrone-block count is the designed one;
- fetching a part is one form submission, verified against the set's
  header echo and archived with its complete acquisition record.
"""

from __future__ import annotations

import gzip
import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator

from stellariso.database.design import (
    DirectoryMatch,
    FamilyAdapter,
    PartDesign,
    PartVerdict,
    ProductDesign,
    SelectionCriteria,
)
from stellariso.exceptions import SourceUnavailableError
from stellariso.models.parsec import blueprint as bp
from stellariso.models.parsec.cmd_form import CmdFieldSet

__all__ = ["ParsecAdapter", "count_blocks"]

_PARTS: tuple[PartDesign, ...] = (
    PartDesign(name="log", filename="output.dat"),
    PartDesign(name="linear", filename="output_linear.dat"),
)

_KIND = "cmd_form_isochrones"


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


class ParsecAdapter(FamilyAdapter):
    family = "parsec"

    # -- enumeration ------------------------------------------------------

    def _design_of_cell(self, cell: bp.Cell) -> ProductDesign:
        return ProductDesign(
            family="parsec",
            collection=cell.set.key,
            label=cell.label,
            kind=_KIND,
            parts=_PARTS,
            facts={"cell": cell},
        )

    def designs(self) -> Iterator[ProductDesign]:
        for cell in bp.all_cells():
            yield self._design_of_cell(cell)

    def committed(self) -> Iterator[ProductDesign]:
        for ts in bp.TRACK_SETS.values():
            for cell in bp.fetch_cells(ts):
                yield self._design_of_cell(cell)

    # -- directory mapping --------------------------------------------------

    def product_of_directory(self, root: Path, directory: Path) -> DirectoryMatch:
        set_key = directory.parent.name
        ts = bp.TRACK_SETS.get(set_key)
        if ts is None:
            return DirectoryMatch(None, "directory outside the blueprint sets")
        label = directory.name
        if label.startswith("aux_"):
            return DirectoryMatch(
                None, "option-variation table outside the uniform design"
            )
        payload = _load_any_payload(directory)
        cell = _cell_of_payload(payload) if payload else None
        labeled = _cell_of_label(ts, label)
        if cell is None:
            cell = labeled
        elif labeled is not None and labeled.label != cell.label:
            return DirectoryMatch(
                None,
                f"payload says cell {cell.label} but directory name says {labeled.label}",
            )
        if cell is None:
            return DirectoryMatch(None, "maps to no designed cell")
        return DirectoryMatch(self._design_of_cell(cell))

    # -- classification -----------------------------------------------------

    def classify_part(
        self, design: ProductDesign, part: PartDesign, directory: Path, manifest: dict
    ) -> PartVerdict:
        cell: bp.Cell = design.facts["cell"]
        reasons: list[str] = []
        table = directory / part.filename
        record_path = directory / (part.filename + ".record.json")
        payload: dict[str, str] = {}
        if not table.exists() and not record_path.exists():
            return PartVerdict.missing()  # nothing archived for this part
        if not record_path.exists():
            reasons.append(f"no acquisition record ({record_path.name})")
        else:
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                reasons.append(f"unreadable acquisition record: {exc}")
            else:
                payload = record.get("request_fields", {})
                reasons.extend(bp.payload_diff(payload, bp.expected_payload(cell, part.name)))
        blocks = count_blocks(table)
        expected_blocks = (
            bp.expected_log_ages() if part.name == "log" else bp.expected_linear_ages()
        )
        if blocks is None:
            reasons.append(f"{part.name}-age table missing or unreadable")
        elif blocks != expected_blocks:
            reasons.append(
                f"{part.name}-age table has {blocks} isochrones, "
                f"design expects {expected_blocks}"
            )
        if reasons:
            return PartVerdict.nonconforming(*reasons)
        return PartVerdict.ok()

    # -- fetching -----------------------------------------------------------

    def fetch_part(
        self,
        design,
        part,
        directory,
        *,
        session=None,
        client=None,
        log: Callable[[str], None] = print,
    ) -> dict:
        if client is None:
            from stellariso.models.parsec.cmd_form import CmdFormClient

            client = CmdFormClient(session=session)
        cell: bp.Cell = design.facts["cell"]
        table = part.filename
        fields = CmdFieldSet.from_overrides(
            **(cell.log_fields() if part.name == "log" else cell.linear_fields())
        )
        log(
            f"submitting form job for {design.relative_dir} ({part.name}-age grid)"
        )
        job = client.submit(fields)
        out = client.fetch_output(job)
        expected = cell.set.verify_header
        if expected and not any(expected in ln for ln in out.comment_lines):
            raise SourceUnavailableError(
                f"{design.relative_dir}: the server's header echo does not "
                f"contain {expected!r}; echo was {list(out.comment_lines[:4])}"
            )
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

    # -- manifest and report --------------------------------------------------

    def family_section(self, design) -> dict:
        cell: bp.Cell = design.facts["cell"]
        return {
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
        }

    def report_header(self, designs) -> list[str]:
        lines = [
            "Source: official CMD 3.9 computation service "
            "(https://stev.oapd.inaf.it/cgi-bin/cmd); the declared "
            "acquisition design is docs/parsec/blueprint.md.",
        ]
        for ts in bp.TRACK_SETS.values():
            lines.append(f"### set {ts.key} — {ts.tier}")
            lines.append(
                f"Tracks: `{ts.track_parsec}` + `track_colibri={ts.track_colibri}`; "
                f"window: {ts.mh_window}"
            )
            supplements = [
                v for v in ts.mh_values if abs(v / bp.MH_STEP - round(v / bp.MH_STEP)) > 1e-9
            ]
            supp_text = (
                "; boundary supplements: " + ", ".join(f"{v:+g}" for v in supplements)
                if supplements
                else ""
            )
            lines.append(
                f"Compositions [M/H]: {ts.mh_low:+g} to {ts.mh_high:+g}, "
                f"step {bp.MH_STEP:g} dex -> {len(ts.mh_values)} values{supp_text}"
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
                f"Designed cells: {len(bp.cells(ts)):,}; fetch-stage target: "
                f"{len(bp.fetch_cells(ts)):,}{target_note}"
            )
        return lines

    def matches_criteria(self, design, criteria: SelectionCriteria) -> bool:
        if not super().matches_criteria(design, criteria):
            return False
        cell: bp.Cell = design.facts["cell"]
        axes = criteria.axes or {}
        for name, wanted in axes.items():
            if name == "mh":
                if isinstance(wanted, (tuple, list)) and len(wanted) == 2:
                    lo, hi = wanted
                    if not (lo - 1e-9 <= cell.mh <= hi + 1e-9):
                        return False
                elif cell.mh not in _as_list(wanted):
                    return False
            elif name == "omega":
                if cell.omega not in _as_list(wanted):
                    return False
            elif name == "eta":
                if cell.eta not in _as_list(wanted):
                    return False
            elif name == "n_inTPC":
                if cell.n_intpc not in _as_list(wanted, cast=int):
                    return False
            elif name == "dust_m":
                if cell.dust_m not in _as_list(wanted):
                    return False
            elif name == "dust_c":
                if cell.dust_c not in _as_list(wanted):
                    return False
            elif name == "lpv":
                if cell.lpv not in _as_list(wanted):
                    return False
            elif name == "tier":
                if cell.set.tier not in _as_list(wanted):
                    return False
            else:
                raise ValueError(
                    f"unknown PARSEC axis filter {name!r} (known: mh, omega, "
                    "eta, n_inTPC, dust_m, dust_c, lpv, tier)"
                )
        return True


def _as_list(value, cast=None):
    values = value if isinstance(value, (tuple, list)) else (value,)
    if cast is not None:
        values = [cast(v) for v in values]
    return values


# -- payload ↔ cell mapping (directory side) ------------------------------------


@lru_cache(maxsize=None)
def _cell_index(ts_key: str) -> dict[tuple, bp.Cell]:
    """Axis tuple -> designed cell, for one set (built once per set)."""
    ts = bp.TRACK_SETS[ts_key]
    return {
        (c.mh, c.omega, c.eta, c.n_intpc, c.dust_m, c.dust_c, c.lpv): c
        for c in bp.cells(ts)
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
    key = next(
        (k for k, ts in bp.TRACK_SETS.items() if (ts.track_parsec, ts.track_colibri) == tracks),
        None,
    )
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


def _cell_of_label(ts: bp.TrackSet, label: str) -> bp.Cell | None:
    """The cell a directory name encodes (fallback when no record)."""
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


# -- the report's declaration lines (per set) ------------------------------------


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
