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

from collections.abc import Iterator
from functools import cache, partial
import gzip
import io
import json
from pathlib import Path
from typing import Any, Callable

import certifi
import requests

from stellariso.database.design import (
    DirectoryMatch,
    FamilyAdapter,
    PartDesign,
    PartVerdict,
    ProductDesign,
    SelectionCriteria,
)
from stellariso.database.signature_cache import SignatureCache
from stellariso.exceptions import SourceUnavailableError
from stellariso.integrity import sha256_file
from stellariso.models import catalog as load_catalog
from stellariso.models.parsec import blueprint as bp
from stellariso.models.parsec.cmd_form import CmdFieldSet, CmdFormClient
from stellariso.registry import references

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
    """PARSEC: form-computed cells of the declared blueprint."""
    family = "parsec"

    # -- enumeration ------------------------------------------------------

    def _design_of_cell(self, cell: bp.Cell) -> ProductDesign:
        return ProductDesign(
            family="parsec",
            collection=cell.set.key,
            release=cell.set.release,
            label=cell.label,
            kind=_KIND,
            parts=_PARTS,
            facts={"cell": cell},
        )

    def designs(self) -> Iterator[ProductDesign]:
        """Every designed cell of every track set (the full blueprint)."""
        # 162k designs: enumerated once per adapter instance, then reused
        cached = self.__dict__.get("_designs_cache")
        if cached is None:
            cached = [self._design_of_cell(cell) for cell in bp.all_cells()]
            self.__dict__["_designs_cache"] = cached
        return iter(cached)

    def committed(self) -> Iterator[ProductDesign]:
        """The cells the current fetch stage commits to acquiring."""
        for ts in bp.TRACK_SETS.values():
            for cell in bp.fetch_cells(ts):
                yield self._design_of_cell(cell)

    # -- directory mapping --------------------------------------------------

    def product_of_directory(self, root: Path, directory: Path) -> DirectoryMatch:
        """Match a directory against the blueprint's set/cell labels."""
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

    def _payload_reasons(
        self, design: ProductDesign, part: PartDesign, directory: Path
    ) -> tuple[list[str], dict[str, str]]:
        """The acquisition-record phase: the missing/unreadable-record
        reasons, and the archived request payload (empty when no record
        survived)."""
        reasons: list[str] = []
        record_path = directory / (part.filename + ".record.json")
        if not record_path.exists():
            return [f"no acquisition record ({record_path.name})"], {}
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"unreadable acquisition record: {exc}"], {}
        payload = record.get("request_fields", {})
        cell: bp.Cell = design.facts["cell"]
        reasons.extend(bp.payload_diff(payload, bp.expected_payload(cell, part.name)))
        return reasons, payload

    def _sha_verdict(
        self,
        table: Path,
        manifest: dict,
        part: PartDesign,
        cache: SignatureCache | None,
    ) -> tuple[str | None, list[str]]:
        """The integrity phase for one archived table: (the mismatch
        reason, the not-verified note). A mismatch is terminal — the
        caller returns immediately; an absent recorded sha256 is a
        warning (nothing to verify against), never a failure."""
        entry = (manifest.get("parts") or {}).get(part.name) or {}
        recorded = entry.get("sha256")
        if recorded is None:
            return None, [
                f"{part.filename}: no sha256 recorded in its MANIFEST; "
                "integrity not verified"
            ]
        actual = cache.sha256(table) if cache is not None else sha256_file(table)
        if actual != recorded:
            return (
                f"{part.filename}: sha256 mismatch — recorded {recorded}, "
                f"file hashes {actual}"
            ), []
        return None, []

    def classify_part(
        self,
        design: ProductDesign,
        part: PartDesign,
        directory: Path,
        manifest: dict,
        cache: SignatureCache | None = None,
    ) -> PartVerdict:
        """A table is conforming when its recorded sha256, its archived
        payload, and its block count match the design (the block count
        comes from a decompressed line scan of the table itself; the
        quick-signature cache serves both answers for unchanged files)."""
        table = directory / part.filename
        record_path = directory / (part.filename + ".record.json")
        if not table.exists() and not record_path.exists():
            return PartVerdict.missing()  # nothing archived for this part
        reasons, _payload = self._payload_reasons(design, part, directory)
        notes: list[str] = []
        blocks: int | None = None
        if table.exists():
            blocks = (
                cache.fact(table, "blocks", lambda: count_blocks(table))
                if cache is not None
                else count_blocks(table)
            )
            mismatch, unverified = self._sha_verdict(table, manifest, part, cache)
            notes.extend(unverified)
            if mismatch:
                return PartVerdict.nonconforming(*reasons, mismatch)
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
        return PartVerdict.ok(*notes)

    # -- fetching -----------------------------------------------------------

    def fetch_part(
        self,
        design: ProductDesign,
        part: PartDesign,
        directory: Path,
        *,
        session: requests.Session | None = None,
        client: CmdFormClient | None = None,
        log: Callable[[str], None] = print,
    ) -> dict:
        """Submit the cell through the CMD form and archive the returned table."""
        if client is None:
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
        with open(directory / (table + ".record.json"), "w", encoding="utf-8", newline="\n") as _f:
            _f.write(json.dumps(out.record(), indent=2, sort_keys=True) + "\n")
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

    def default_session(self, database: Path) -> requests.Session:
        """A session with the form host's missing TLS intermediate
        appended to the standard trust store, so verification stays ON
        (the combined bundle is written under ``<database>/.tls/``)."""
        bundle_name = load_catalog("parsec").get("ca_bundle")
        if not bundle_name:
            return None
        model_dir = Path(__file__).parent
        intermediate = model_dir / bundle_name
        if not intermediate.exists():
            raise SourceUnavailableError(
                f"catalog of 'parsec' declares CA bundle {bundle_name!r}, "
                f"which is missing from {model_dir}"
            )
        tls_dir = Path(database) / ".tls"
        tls_dir.mkdir(parents=True, exist_ok=True)
        combined = tls_dir / "parsec-ca-bundle.pem"
        combined.write_bytes(
            Path(certifi.where()).read_bytes() + b"\n" + intermediate.read_bytes()
        )
        session = requests.Session()
        session.headers["User-Agent"] = "stellariso (isochrone database builder)"
        session.verify = str(combined)
        return session

    def fetch_client(self, session: requests.Session | None = None) -> CmdFormClient:
        """The form client shared by one build run (default_session's bundle honored)."""
        return CmdFormClient(session=session)

    def manifest_fields(self, design: ProductDesign) -> dict:
        """Citation list for the computed-service channel."""
        return {
            "source_class": "official_computed",
            "note": (
                "official CMD web form (https://stev.oapd.inaf.it/cgi-bin/cmd); "
                "one blueprint cell: both age grids in this directory"
            ),
            "format": "cmd_table_3_9",
            "physics": None,
            "references": [r.citation for r in references("parsec")],
        }

    def family_section(self, design: ProductDesign) -> dict:
        """The blueprint cell the product realizes, in full."""
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

    def report_header(self, designs: list[ProductDesign]) -> list[str]:
        """Report header naming the computation service and the staged design."""
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

    def matches_criteria(
        self, design: ProductDesign, criteria: SelectionCriteria
    ) -> bool:
        """Narrow selection to the blueprint axes ([M/H], rotation, eta, dust, LPV)."""
        if not super().matches_criteria(design, criteria):
            return False
        cell: bp.Cell = design.facts["cell"]
        for name, wanted in (criteria.axes or {}).items():
            if not _axis_matches(cell, name, wanted):
                return False
        return True



_AXIS_FILTERS = ("mh", "omega", "eta", "n_inTPC", "dust_m", "dust_c", "lpv", "tier")


def _axis_matches(cell: bp.Cell, name: str, wanted: Any) -> bool:
    """Whether one blueprint axis filter accepts the cell."""
    if name == "mh":
        # a 2-tuple is an inclusive range; anything else a value list
        if isinstance(wanted, (tuple, list)) and len(wanted) == 2:
            lo, hi = wanted
            return lo - 1e-9 <= cell.mh <= hi + 1e-9
        return cell.mh in _as_list(wanted)
    if name == "n_inTPC":
        return cell.n_intpc in _as_list(wanted, cast=int)
    if name == "tier":
        return cell.set.tier in _as_list(wanted)
    for axis in ("omega", "eta", "dust_m", "dust_c", "lpv"):
        if name == axis:
            return getattr(cell, axis) in _as_list(wanted)
    raise ValueError(
        f"unknown PARSEC axis filter {name!r} (known: {_AXIS_FILTERS})"
    )


def _as_list(value: Any, cast: Callable[[Any], Any] | None = None) -> tuple:
    values = value if isinstance(value, (tuple, list)) else (value,)
    if cast is not None:
        values = [cast(v) for v in values]
    return values


# -- payload ↔ cell mapping (directory side) ------------------------------------


@cache
def _cell_index(ts_key: str) -> dict[tuple, bp.Cell]:
    """Axis tuple -> designed cell, for one set (built once per set)."""
    ts = bp.TRACK_SETS[ts_key]
    return {
        (c.mh, c.omega, c.eta, c.n_intpc, c.dust_m, c.dust_c, c.lpv): c
        for c in bp.cells(ts)
    }


def _find_cell(
    ts: bp.TrackSet,
    *,
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
    return _find_cell(
        bp.TRACK_SETS[key],
        mh=mh, omega=omega, eta=eta, n_intpc=n_intpc,
        dust_m=dust_m, dust_c=dust_c, lpv=lpv,
    )


def _cell_of_label(ts: bp.TrackSet, label: str) -> bp.Cell | None:
    """The cell a directory name encodes (fallback when no record)."""
    text = label
    if ts.label_prefix:
        if not text.startswith(ts.label_prefix):
            return None
        text = text[len(ts.label_prefix) :]

    # strip the optional axis suffixes (fixed emitted order, but parsed
    # tolerantly from the end); dust names carry no underscores.
    axes = _strip_axis_suffixes(text)
    text = axes["text"]
    eta = axes.get("eta")
    omega = axes.get("omega")
    n_intpc = axes.get("n_intpc")
    dust_m = axes.get("dust_m")
    dust_c = axes.get("dust_c")
    lpv = axes.get("lpv")

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
    return _find_cell(
        ts,
        mh=mh, omega=omega, eta=eta, n_intpc=n_intpc,
        dust_m=dust_m, dust_c=dust_c, lpv=lpv,
    )


def _strip_axis_suffixes(label: str) -> dict[str, Any]:
    """Peel the optional axis suffixes off a cell label, from the end.

    Returns the remaining text under ``"text"`` plus every axis value
    peeled off (each at most once, in emitted order).
    """
    def strip_listed(text: str, *, marker: str, values: tuple[str, ...],
                     cast: Callable[[str], Any]) -> tuple[Any, str] | None:
        if not text.endswith(tuple(f"{marker}{v}" for v in values)):
            return None
        head, _, value = text.rpartition(marker)
        return cast(value), head

    def strip_numbered(text: str, *, marker: str) -> tuple[float, str] | None:
        sep = text.rfind(marker)
        if sep == -1 or "." not in text[sep + 2 :]:
            return None
        try:
            return float(text[sep + 2 :]), text[:sep]
        except ValueError:
            return None

    strippers: tuple[tuple[str, Callable[[str], tuple[Any, str] | None]], ...] = (
        ("lpv", partial(strip_listed, marker="_lpv", values=bp.LPV_VALUES, cast=str)),
        ("dust_c", partial(strip_listed, marker="_dC", values=bp.DUST_C_VALUES, cast=str)),
        ("dust_m", partial(strip_listed, marker="_dM", values=bp.DUST_M_VALUES, cast=str)),
        ("n_intpc", partial(strip_listed, marker="_n", values=bp.N_INTPC_VALUES, cast=int)),
        ("eta", partial(strip_numbered, marker="_e")),
        ("omega", partial(strip_numbered, marker="_w")),
    )
    out: dict[str, Any] = {"text": label}
    while True:
        for axis, strip in strippers:
            if axis in out:
                continue
            peeled = strip(out["text"])
            if peeled is not None:
                out[axis], out["text"] = peeled
                break
        else:
            return out


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
