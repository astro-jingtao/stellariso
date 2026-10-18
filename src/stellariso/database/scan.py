"""The two-state scanner: measure a database against every design.

Pure local I/O. For each family adapter, every product directory under
``<database>/<family>/`` is mapped into the design (payload authority
for form families, catalog identity for package families); directories
mapping nowhere are ``superseded`` and listed with their reasons. Every
committed design then gets one :class:`ProductScan` whose parts carry
the per-part verdicts:

- ``complete`` — every designed part ``ok``;
- ``incomplete`` — any part missing or nonconforming, with the per-part
  detail (``log ok; linear missing``) and, for nonconforming parts, the
  reasons and a manual-review mark.

The report is the review artifact: it plans automatic work (missing
parts of clean products) and lists what stays with a human
(nonconforming data, superseded directories). Marked data is never
deleted or refetched by it.

The historical four-state vocabulary maps onto this exactly —
``complete`` → complete; ``log_only`` → incomplete (log ok, linear
missing); ``refetch`` → incomplete with a nonconforming part, manual
review; ``pending`` → incomplete, all parts missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stellariso.database.design import (
    FamilyAdapter,
    PartVerdict,
    ProductDesign,
    adapter_for,
    adapter_families,
)
from stellariso.database.manifest import (
    ManifestError,
    read_manifest,
    utc_now_iso,
)

__all__ = [
    "ProductScan",
    "FamilyScan",
    "DatabaseReport",
    "scan_database",
    "render_markdown",
    "render_summary",
    "report_json",
]


@dataclass
class ProductScan:
    """The two-state verdict for one designed product of one database."""

    design: ProductDesign
    directory: Path | None
    parts: dict[str, PartVerdict]
    blocked_reason: str | None = None
    manifest_warning: str | None = None

    @property
    def state(self) -> str:
        if self.parts and all(v.kind == "ok" for v in self.parts.values()):
            return "complete"
        return "incomplete"

    @property
    def needs_review(self) -> bool:
        return self.blocked_reason is not None or any(
            v.kind == "nonconforming" for v in self.parts.values()
        )

    @property
    def missing_parts(self) -> list[str]:
        return [name for name, v in self.parts.items() if v.kind == "missing"]

    @property
    def nonconforming_parts(self) -> list[str]:
        return [name for name, v in self.parts.items() if v.kind == "nonconforming"]

    def detail(self) -> str:
        """The per-product line body: ``complete`` or the part detail."""
        if self.state == "complete":
            warnings = [w for v in self.parts.values() for w in v.warnings]
            text = "complete"
            if warnings:
                text += " (warning: " + "; ".join(warnings) + ")"
            return text
        if self.blocked_reason:
            return f"incomplete — {self.blocked_reason}"
        bits = []
        for part in self.design.parts:
            verdict = self.parts[part.name]
            if verdict.kind == "ok":
                bits.append(f"{part.name} ok")
            elif verdict.kind == "missing":
                bits.append(f"{part.name} missing")
            else:
                bits.append(
                    f"{part.name} nonconforming: {'; '.join(verdict.reasons)}"
                )
        text = "incomplete (" + "; ".join(bits) + ")"
        if self.needs_review:
            text += " — manual review"
        return text


@dataclass
class FamilyScan:
    """One family's measurement: header, product scans, superseded list."""

    family: str
    header: list[str]
    products: dict[str, ProductScan]
    committed_keys: set[str]
    designed_count: int
    superseded: list[dict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"complete": 0, "incomplete": 0}
        for key, scan in self.products.items():
            if key in self.committed_keys:
                out[scan.state] += 1
        return out

    def archived_beyond_target(self) -> list[ProductScan]:
        return [scan for key, scan in self.products.items() if key not in self.committed_keys]

    def review_products(self) -> list[ProductScan]:
        return sorted(
            (s for s in self.products.values() if s.needs_review),
            key=lambda s: s.design.key,
        )

    def auto_fetches(self) -> list[tuple[ProductScan, str]]:
        """Missing parts the builder will fetch without asking.

        Products needing review are excluded entirely: a checksum or
        design mismatch voids the product for automatic completion, and
        whether its data is re-fetched is a human decision.
        """
        out: list[tuple[ProductScan, str]] = []
        for key, scan in sorted(self.products.items()):
            if key not in self.committed_keys or scan.needs_review:
                continue
            for name in scan.missing_parts:
                out.append((scan, name))
        return out


@dataclass
class DatabaseReport:
    """The full measurement of one database against every design."""

    database: Path
    generated_at: str
    families: dict[str, FamilyScan] = field(default_factory=dict)

    def products_by_state(self, states=("complete", "incomplete")) -> list[ProductScan]:
        return [
            scan
            for family in self.families.values()
            for scan in family.products.values()
            if scan.state in states
        ]

    def incomplete_reasons(self, family: str | None = None) -> dict[str, list[str]]:
        """Design key → the reasons its product is incomplete."""
        out: dict[str, list[str]] = {}
        scopes = [self.families[family]] if family else list(self.families.values())
        for fam in scopes:
            for key, scan in sorted(fam.products.items()):
                if scan.state == "complete":
                    continue
                reasons = [r for v in scan.parts.values() for r in v.reasons]
                if scan.blocked_reason:
                    reasons.append(scan.blocked_reason)
                out[f"{fam.family}/{key}"] = reasons
        return out

    def review_products(self) -> list[ProductScan]:
        return [s for family in self.families.values() for s in family.review_products()]

    def auto_fetches(self, family: str | None = None) -> list[tuple[ProductScan, str]]:
        scopes = [self.families[family]] if family else list(self.families.values())
        return [item for fam in scopes for item in fam.auto_fetches()]

    def all_superseded(self) -> list[dict]:
        out: list[dict] = []
        for family in self.families.values():
            out.extend({"family": family.family, **entry} for entry in family.superseded)
        return out

    def totals(self) -> dict[str, int]:
        complete = incomplete = review = 0
        for family in self.families.values():
            counts = family.counts()
            complete += counts["complete"]
            incomplete += counts["incomplete"]
            review += len(family.review_products())
        return {
            "complete": complete,
            "incomplete": incomplete,
            "needs_review": review,
            "missing_part_fetches": len(self.auto_fetches()),
            "superseded": len(self.all_superseded()),
        }


def _read_product_manifest(directory: Path) -> tuple[dict, str | None]:
    try:
        return read_manifest(directory / "MANIFEST.json"), None
    except ManifestError as exc:
        return {}, f"MANIFEST.json unreadable ({exc})"


def _scan_product(
    root: Path,
    adapter: FamilyAdapter,
    design: ProductDesign,
    directory: Path | None,
    *,
    verify: bool = True,
) -> ProductScan:
    if directory is not None:
        manifest, warning = _read_product_manifest(directory)
        parts = {
            part.name: adapter.classify_part(
                design, part, directory, manifest, verify=verify
            )
            for part in design.parts
        }
        return ProductScan(design, directory, parts, manifest_warning=warning)
    parts = {part.name: PartVerdict.missing() for part in design.parts}
    expected = root / design.relative_dir
    blocked = None
    if expected.is_dir():
        blocked = (
            "directory exists at the designed path but does not map to this "
            "design (see the superseded list) — resolve it by hand before "
            "anything is fetched here"
        )
    return ProductScan(design, None, parts, blocked_reason=blocked)


def scan_database(
    database: str | Path,
    *,
    families: list[str] | None = None,
    verify_checksums: bool = True,
) -> DatabaseReport:
    """Scan a database root against every family's design (two-state).

    ``verify_checksums=False`` classifies present files without
    re-hashing them (the rebuild-trust knob); conformance checks still
    run.
    """
    root = Path(database)
    report = DatabaseReport(database=root, generated_at=utc_now_iso())
    for family in families if families is not None else adapter_families():
        adapter = adapter_for(family)
        designs = list(adapter.designs())
        committed = list(adapter.committed())

        located: dict[str, tuple[ProductDesign, Path]] = {}
        superseded: list[dict] = []
        family_root = root / family
        if family_root.is_dir():
            for directory in sorted(p for p in family_root.glob("*/*") if p.is_dir()):
                match = adapter.product_of_directory(root, directory)
                rel = directory.relative_to(root).as_posix()
                if match.design is None:
                    superseded.append(
                        {
                            "directory": rel,
                            "reason": match.superseded_reason
                            or "maps to no designed product",
                        }
                    )
                elif match.design.key in located:
                    superseded.append(
                        {
                            "directory": rel,
                            "reason": (
                                f"duplicate directory for "
                                f"{match.design.relative_dir} (already at "
                                f"{located[match.design.key][1].relative_to(root).as_posix()})"
                            ),
                        }
                    )
                else:
                    located[match.design.key] = (match.design, directory)

        products: dict[str, ProductScan] = {}
        for design in committed:
            entry = located.get(design.key)
            products[design.key] = _scan_product(
                root,
                adapter,
                entry[0] if entry else design,
                entry[1] if entry else None,
                verify=verify_checksums,
            )
        for key, (design, directory) in sorted(located.items()):
            if key not in products:
                products[key] = _scan_product(
                    root, adapter, design, directory, verify=verify_checksums
                )

        report.families[family] = FamilyScan(
            family=family,
            header=adapter.report_header(designs),
            products=products,
            committed_keys={d.key for d in committed},
            designed_count=len(designs),
            superseded=superseded,
        )
    return report


# -- rendering ------------------------------------------------------------------


def _family_block(family: FamilyScan) -> list[str]:
    committed = family.counts()
    review = len(family.review_products())
    beyond = family.archived_beyond_target()
    lines = [f"## {family.family}", ""]
    lines.extend(family.header)
    lines.append("")
    lines.append(
        f"Designed {family.designed_count:,} products; committed target: "
        f"{len(family.committed_keys):,}."
    )
    lines.append(
        f"Status over the committed target: complete {committed['complete']}, "
        f"incomplete {committed['incomplete']} ({review} needing manual review)."
    )
    if beyond:
        lines.append(
            f"Beyond the committed target: {len(beyond)} archived designed "
            "products (counted, not listed)."
        )
    lines.append("")
    lines.append(f"### Products — {len(family.products):,}")
    for key in sorted(family.products):
        scan = family.products[key]
        lines.append(f"- {key} — {scan.detail()}")
        if scan.manifest_warning:
            lines.append(f"  - {scan.manifest_warning}")
    review_scans = family.review_products()
    if review_scans:
        lines.append("")
        lines.append(f"### Incomplete, manual review — {len(review_scans)}")
        for scan in review_scans:
            lines.append(f"- {scan.design.key} — {scan.detail()}")
    if family.superseded:
        lines.append("")
        lines.append(f"### Superseded directories — {len(family.superseded)}")
        for entry in family.superseded:
            lines.append(f"- `{entry['directory']}` — {entry['reason']}")
    lines.append("")
    return lines


def render_markdown(report: DatabaseReport) -> str:
    """The full review artifact: declarations, verdicts, reasons, lists."""
    lines = [
        "# stellariso database status",
        "",
        f"Database: `{report.database}`",
        f"Generated: {report.generated_at} (UTC)",
        "",
    ]
    for family in report.families.values():
        lines.extend(_family_block(family))
    totals = report.totals()
    fetch_plan = _fetch_plan(report)
    lines.extend(
        [
            "## Totals",
            "",
            f"- complete {totals['complete']}, incomplete {totals['incomplete']} "
            f"({totals['needs_review']} needing manual review)",
            f"- automatic fetch work: {fetch_plan['downloads']} archive downloads "
            f"({_bytes_text(fetch_plan['bytes'])}), {fetch_plan['submissions']} form "
            "submissions",
            f"- superseded directories: {totals['superseded']}",
            "",
            "Nonconforming data is never auto-refetched and superseded directories "
            "are never deleted by this report; both stay with the database owner.",
        ]
    )
    return "\n".join(lines) + "\n"


def _bytes_text(size: int | None) -> str:
    return f"{size:,} bytes" if size is not None else "size unknown"


def _fetch_plan(report: DatabaseReport) -> dict:
    """The automatic work split by channel, via the adapters' costs."""
    downloads = submissions = 0
    bytes_total: int | None = 0
    for scan, part_name in report.auto_fetches():
        adapter = adapter_for(scan.design.family)
        cost = adapter.fetch_cost(scan.design, scan.design.part_named(part_name))
        if cost.get("kind") == "download":
            downloads += 1
            size = cost.get("size_bytes")
            bytes_total = None if (size is None or bytes_total is None) else bytes_total + size
        else:
            submissions += 1
    return {"downloads": downloads, "submissions": submissions, "bytes": bytes_total}


def render_summary(report: DatabaseReport) -> str:
    """The console digest: one line per family plus the totals."""
    lines = [f"database: {report.database}"]
    for family in report.families.values():
        counts = family.counts()
        review = len(family.review_products())
        lines.append(
            f"{family.family}: {len(family.committed_keys)} committed products — "
            f"complete {counts['complete']}, incomplete {counts['incomplete']} "
            f"({review} review, {len(family.superseded)} superseded)"
        )
    totals = report.totals()
    lines.append(
        f"totals: complete {totals['complete']}, incomplete {totals['incomplete']}; "
        f"auto fetches {totals['missing_part_fetches']}; review {totals['needs_review']}; "
        f"superseded {totals['superseded']}"
    )
    return "\n".join(lines)


def report_json(report: DatabaseReport) -> dict:
    """The machine-readable twin of the markdown report."""
    families = {}
    for family in report.families.values():
        counts = family.counts()
        families[family.family] = {
            "designed": family.designed_count,
            "committed": len(family.committed_keys),
            **counts,
            "needs_review": len(family.review_products()),
            "archived_beyond_target": len(family.archived_beyond_target()),
            "missing_part_fetches": len(family.auto_fetches()),
            "products": {
                key: {
                    "state": scan.state,
                    "directory": (
                        scan.directory.relative_to(report.database).as_posix()
                        if scan.directory
                        else None
                    ),
                    "parts": {
                        name: {
                            "kind": verdict.kind,
                            "reasons": list(verdict.reasons),
                            "warnings": list(verdict.warnings),
                        }
                        for name, verdict in scan.parts.items()
                    },
                    **({"blocked_reason": scan.blocked_reason} if scan.blocked_reason else {}),
                    **({"manifest_warning": scan.manifest_warning} if scan.manifest_warning else {}),
                }
                for key, scan in sorted(family.products.items())
            },
            "superseded": family.superseded,
        }
    return {
        "database": str(report.database),
        "generated_at": report.generated_at,
        "families": families,
        "totals": report.totals(),
    }
