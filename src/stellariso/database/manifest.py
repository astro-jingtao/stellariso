"""MANIFEST v2: one shape for every product, plus the legacy read bridge.

Schema ``stellariso-manifest/2`` describes a product directory's identity
and its acquisition units ("parts") uniformly across families::

    {
      "schema": "stellariso-manifest/2",
      "family": "parsec", "release": "...", "label": "...", "kind": "...",
      "source_class": "...", "note": "...", "format": "...",
      "references": [...],
      "parts": {
        "log":    {"file": "output.dat", "sha256": "...", "size_bytes": 1,
                   "n_data_rows": 177, "retrieved_at": "...",
                   "record": "output.dat.record.json", "url": "..."},
        ...
      },
      "family_section": {...},   # optional, family-specific
      "extracted": true, "n_data_files": 2   # package products: local
                                             # materialization state
    }

Reading is version-tolerant, writing is not:

- **Read side** — :func:`read_manifest` (and :func:`normalize`) accept
  both v2 and the historical shapes, returning a v2-shaped view. The
  legacy shapes are: the run-4 package product (a flat top-level
  ``sha256``/``url``/``size_bytes`` describing the archive), the run-4
  form product (the same flat keys describing the log table), and the
  blueprint form product (a ``blueprint`` section whose ``parts`` map
  supersedes the flat keys). The bridge is pure: it never writes.
- **Write side** — :func:`write_manifest` stamps the current schema and
  is the only way any code path persists a MANIFEST; legacy shapes are
  never written.
- **Upgrade** — :func:`upgrade_manifests` rewrites every product
  MANIFEST of a database to clean v2, atomically per product, without
  touching one byte of archived data. A manifest whose information
  cannot be carried over losslessly is reported (with reasons) and left
  untouched for a human decision — the bridge keeps it readable either
  way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stellariso.exceptions import ManifestError

__all__ = [
    "SCHEMA",
    "ManifestUpgradeFailure",
    "ManifestUpgradeReport",
    "upgrade_manifests",
    "is_v2",
    "load_raw",
    "normalize",
    "primary_part",
    "read_manifest",
    "write_manifest",
    "utc_now_iso",
]

#: The manifest schema every write path produces.
SCHEMA = "stellariso-manifest/2"

#: Top-level keys of the legacy shapes that v2 carries inside ``parts``
#: (dropped by the upgrade; preserved verbatim by the read bridge).
_LEGACY_MOVED_KEYS = (
    "sha256",
    "size_bytes",
    "url",
    "retrieved_at",
    "expected_size_bytes",
    "n_data_rows",
    "acquisition_record",
    "blueprint",
)


def utc_now_iso() -> str:
    """The current UTC instant in the manifests' timestamp format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_raw(path: Path) -> dict:
    """Load a MANIFEST.json file as stored, with no normalization."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"{path}: unreadable manifest: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path}: manifest is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: manifest must be a JSON object")
    return raw


def is_v2(raw: dict) -> bool:
    """Whether a loaded manifest already carries the current schema."""
    return raw.get("schema") == SCHEMA


def _bridge_parts(raw: dict) -> dict:
    """Synthesize the v2 ``parts`` map from a legacy manifest.

    The three historical shapes, in authority order:

    - blueprint form product — ``blueprint.parts`` is the parts map
      verbatim; the flat top-level keys are its run-4 shadow;
    - run-4 form product (``kind`` ``cmd_form_isochrones`` or a flat
      ``acquisition_record``) — the flat keys describe the log table;
    - package product (any other shape with a flat ``sha256``) — the
      flat keys describe the archive. The archive *filename* is not
      recorded in these manifests; the family design names it, so the
      synthesized entry carries no ``file`` key.

    Manually registered local files (``kind`` ``local_user_files``) have
    no checksummed parts: they keep their ``files`` list and get an
    empty parts map.
    """
    blueprint = raw.get("blueprint")
    parts: dict = {}
    if isinstance(raw.get("parts"), dict):
        # defensive: a parts map without a schema stamp is already parted
        parts = {name: dict(entry) for name, entry in raw["parts"].items()}
    elif isinstance(blueprint, dict) and isinstance(blueprint.get("parts"), dict):
        parts = {name: dict(entry) for name, entry in blueprint["parts"].items()}
    kind = raw.get("kind")
    if "log" not in parts and (
        kind == "cmd_form_isochrones" or raw.get("acquisition_record")
    ):
        parts["log"] = {
            key: raw[key]
            for key in ("sha256", "size_bytes", "n_data_rows", "retrieved_at", "url")
            if raw.get(key) is not None
        }
        parts["log"]["file"] = "output.dat"
        parts["log"]["record"] = raw.get("acquisition_record") or "output.dat.record.json"
    elif not parts and kind != "local_user_files" and raw.get("sha256"):
        parts["archive"] = {
            key: raw[key]
            for key in ("sha256", "size_bytes", "expected_size_bytes", "retrieved_at", "url")
            if raw.get(key) is not None
        }
    return parts


def normalize(raw: dict) -> dict:
    """A v2-shaped view of any manifest, current or legacy (pure).

    Legacy top-level keys stay in the view (the bridge is a compatibility
    lens, not a rewrite); readers take part facts through ``parts`` and
    identity through the top level. A manifest declaring an unknown
    schema raises :class:`ManifestError` — a newer manifest version is a
    visible incompatibility, not something to guess around.
    """
    schema = raw.get("schema")
    if schema is not None and schema != SCHEMA:
        raise ManifestError(
            f"manifest schema {schema!r} is not known here (current: {SCHEMA!r}); "
            "a newer stellariso wrote this database"
        )
    if schema == SCHEMA:
        return dict(raw)
    view = dict(raw)
    view["parts"] = _bridge_parts(raw)
    return view


def read_manifest(path: Path) -> dict:
    """Load one MANIFEST.json and return its v2-shaped view."""
    return normalize(load_raw(path))


def write_manifest(path: Path, manifest: dict) -> None:
    """Persist a manifest as current-schema v2, atomically.

    The schema key is stamped here — every write path in the library goes
    through this function, so no code can persist a legacy shape.
    """
    payload = dict(manifest)
    payload["schema"] = SCHEMA
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    tmp.replace(path)


def primary_part(manifest: dict) -> str | None:
    """The part a manifest's product is primarily identified by.

    ``archive`` for package products, ``log`` for form products, the
    first name in sorted order otherwise, ``None`` when no part exists.
    Used for the identity-facing fields of the read facade and the
    root inventory.
    """
    parts = manifest.get("parts") or {}
    if not parts:
        return None
    for name in ("archive", "log"):
        if name in parts:
            return name
    return sorted(parts)[0]


# -- the whole-database upgrade (write side converges on v2) --------------------


@dataclass(frozen=True)
class ManifestUpgradeFailure:
    """One manifest the upgrade refused to touch, and why."""

    directory: str
    reasons: tuple[str, ...]


@dataclass
class ManifestUpgradeReport:
    """The outcome of one :func:`upgrade_manifests` run."""

    database: Path
    dry_run: bool
    upgraded: list[str] = field(default_factory=list)
    already_current: list[str] = field(default_factory=list)
    failed: list[ManifestUpgradeFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _upgrade_one(raw: dict) -> tuple[dict, tuple[str, ...]]:
    """Build the clean v2 form of one legacy manifest, or refuse it.

    Returns the new manifest and, when it is non-empty, the reasons the
    manifest cannot be upgraded losslessly.
    """
    reasons: list[str] = []
    if not raw.get("family"):
        reasons.append("manifest carries no family identity")
    blueprint = raw.get("blueprint")
    parts = raw.get("blueprint", {}).get("parts", {}) if isinstance(blueprint, dict) else {}
    log_sha = parts.get("log", {}).get("sha256") if isinstance(parts.get("log"), dict) else None
    top_sha = raw.get("sha256")
    if log_sha and top_sha and log_sha != top_sha:
        reasons.append(
            f"conflicting sha256 for the log part: top-level {top_sha} vs "
            f"blueprint {log_sha}"
        )
    if reasons:
        return {}, tuple(reasons)

    view = normalize(raw)
    upgraded = {key: value for key, value in view.items() if key not in _LEGACY_MOVED_KEYS}
    upgraded["parts"] = view["parts"]
    if isinstance(blueprint, dict):
        upgraded["family_section"] = {
            key: value for key, value in blueprint.items() if key != "parts"
        }
    return upgraded, ()


def _carries_equivalently(stamped: dict, raw: dict) -> bool:
    """Whether a stamped v2 manifest carries everything a legacy one did.

    The upgrade's drop/move rules, checked rather than assumed: identity
    keys survive verbatim, the parts map survives intact, and the
    blueprint section survives as ``family_section`` minus its parts.
    """
    view = normalize(raw)
    ignored = set(_LEGACY_MOVED_KEYS) | {"schema", "parts", "family_section"}
    keys = (set(view) | set(stamped)) - ignored
    if any(view.get(k) != stamped.get(k) for k in keys):
        return False
    if stamped.get("parts") != view.get("parts"):
        return False
    blueprint = raw.get("blueprint")
    if isinstance(blueprint, dict):
        expected = {k: v for k, v in blueprint.items() if k != "parts"}
    else:
        expected = stamped.get("family_section")
    return (stamped.get("family_section") or None) == (expected or None)


def upgrade_manifests(
    database: str | Path, *, dry_run: bool = False, log=print
) -> ManifestUpgradeReport:
    """Rewrite every product MANIFEST of a database to clean v2.

    Each product is rewritten atomically (``.tmp`` then replace); the
    archived data files are never touched. A manifest whose information
    cannot be carried over without loss — an unknown schema, a missing
    identity, flat keys contradicting the blueprint parts — is reported
    with its reasons and left exactly as it was: the read bridge keeps
    it usable either way, and the disposition (edit by hand, or fetch
    the product anew) stays with the database owner.

    The losslessness of each rewrite is verified mechanically: the
    normalized view of the written form must equal the normalized view
    of the original. ``dry_run=True`` computes and reports everything
    but writes nothing.
    """
    root = Path(database)
    report = ManifestUpgradeReport(database=root, dry_run=dry_run)
    for manifest_path in sorted(root.glob("*/*/*/MANIFEST.json")):
        rel = manifest_path.parent.relative_to(root).as_posix()
        try:
            raw = load_raw(manifest_path)
        except ManifestError as exc:
            report.failed.append(ManifestUpgradeFailure(rel, (str(exc),)))
            continue
        if is_v2(raw):
            report.already_current.append(rel)
            continue
        try:
            upgraded, reasons = _upgrade_one(raw)
        except ManifestError as exc:
            report.failed.append(ManifestUpgradeFailure(rel, (str(exc),)))
            continue
        if reasons:
            report.failed.append(ManifestUpgradeFailure(rel, reasons))
            log(f"NOTICE {rel}: not upgraded — {'; '.join(reasons)}")
            continue
        if not _carries_equivalently({**upgraded, "schema": SCHEMA}, raw):
            # Defensive: the equivalence is structural; if a shape ever
            # defeats it, refuse rather than write a lossy manifest.
            report.failed.append(
                ManifestUpgradeFailure(rel, ("upgrade would lose information",))
            )
            continue
        if not dry_run:
            write_manifest(manifest_path, upgraded)
        report.upgraded.append(rel)
    return report
