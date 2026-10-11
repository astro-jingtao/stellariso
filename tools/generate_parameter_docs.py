"""Generate docs/unified-parameters.md from the unified-parameter registry.

The registry JSON (src/stellariso/registry/unified_parameters.json) is the
single source of truth; this tool renders it into the human-readable
reference document. Run it after every registry edit:

    python tools/generate_parameter_docs.py           # write the doc
    python tools/generate_parameter_docs.py --check   # verify it is current
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "src" / "stellariso" / "registry" / "unified_parameters.json"
DOC = REPO_ROOT / "docs" / "unified-parameters.md"

ROLE_LABELS = {
    "axis": "axis (varies across the published grid)",
    "fixed": "fixed (known value for the whole product)",
    "derived": "derived (stated relation)",
    "implicit": "implicit (used by the model, not recoverable)",
    "unknown": "unknown (not verified)",
    "not_applicable": "not applicable under this physics",
}


def _value_source(entry: dict) -> str:
    if "alternatives" in entry:
        return " or ".join(_value_source(alt) for alt in entry["alternatives"])
    parts = []
    if "value_from" in entry:
        parts.append(f"file value `{entry['value_from']}`")
    if "values_from" in entry:
        parts.append(f"file values `{entry['values_from']}`")
    if "value" in entry:
        parts.append(f"`{entry['value']}`")
    if "values" in entry:
        parts.append("`" + ", ".join(str(v) for v in entry["values"]) + "`")
    if "relation" in entry:
        params = entry.get("relation_parameters", {})
        plist = ", ".join(f"{k}={v}" for k, v in params.items())
        parts.append(f"relation `{entry['relation']}`" + (f" ({plist})" if plist else ""))
    if "when" in entry:
        parts.append(f"only when {entry['when']}")
    return "; ".join(parts) if parts else "—"


def _escape(text: str | None) -> str:
    if not text:
        return "—"
    return text.replace("|", "\\|").replace("\n", " ")


def render(reg: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Unified parameters and field mappings")
    add("")
    add(
        "This document records the unified vocabulary every data source maps "
        "into, each source's own fields and physical parameters, and the "
        "mapping between the two layers. It is generated from the registry "
        "data file `src/stellariso/registry/unified_parameters.json`, which "
        "is the single source of truth for the library code as well — the "
        "backends load their field specs, phase mappings, and static "
        "parameter knowledge from it."
    )
    add("")
    add("Regenerate this document after editing the registry:")
    add("")
    add("```bash")
    add("python tools/generate_parameter_docs.py")
    add("```")
    add("")

    add("## Unified evolutionary stages")
    add("")
    add(
        "The coarse stage vocabulary shared by all sources. Native phase "
        "codes map into these; unmapped codes resolve to `unknown` with a "
        "warning, never to a guess."
    )
    add("")
    for stage in reg["unified_phases"]:
        add(f"- `{stage}`")
    add("")

    add("## Unified field vocabulary")
    add("")
    add("| Unified field | Unit | Representation | Description |")
    add("|---|---|---|---|")
    for f in reg["unified_fields"]:
        add(
            f"| `{f['name']}` | {_escape(f['unit'])} | {f['representation']} "
            f"| {_escape(f['description'])} |"
        )
    add("")

    add("## Physical parameter vocabulary")
    add("")
    add(
        "Physical parameters a model product can carry. The role a "
        "parameter plays in a specific source (axis, fixed, derived, "
        "implicit, not applicable) is listed per source below; the value "
        "notions — available grid values, fixed values, selection pins — "
        "stay separate in the API."
    )
    add("")
    add("| Parameter | Unit | Convention | Description |")
    add("|---|---|---|---|")
    for p in reg["physical_parameters"]:
        add(
            f"| `{p['name']}` | {_escape(p['unit'])} | {_escape(p['convention'])} "
            f"| {_escape(p['description'])} |"
        )
    add("")

    for name, backend in reg["backends"].items():
        title = {"mist": "MIST", "parsec": "PARSEC / Padova"}.get(name, name)
        add(f"## {title} (`{name}`)")
        add("")
        add(f"Field mapping version: `{backend['mapping_version']}`.")
        add("")
        for note in backend["notes"]:
            add(f"- {note}")
        add("")

        add("### Field mappings")
        add("")
        add("| Unified field | Native column | Origin | Transformation | Notes |")
        add("|---|---|---|---|---|")
        for m in backend["field_mappings"]:
            add(
                f"| `{m['unified']}` | `{m['native']}` | {m['origin']} "
                f"| {_escape(m.get('transformation'))} "
                f"| {_escape(m.get('description'))} |"
            )
        add("")

        add("### Phase mapping")
        add("")
        add("| Native code | Official meaning | Unified stage |")
        add("|---|---|---|")
        meanings = backend["phase_code_meanings"]
        for code, stage in backend["phase_mapping"].items():
            add(f"| {code} | {_escape(meanings.get(code))} | `{stage}` |")
        add("")

        if "eep_anchors" in backend:
            add("### Primary EEP anchors")
            add("")
            add("| Anchor | EEP number |")
            add("|---|---|")
            for anchor, eep in backend["eep_anchors"].items():
                add(f"| {anchor} | {eep} |")
            add("")

        add("### Physical parameters")
        add("")
        add("| Parameter | Role | Value / source | Notes |")
        add("|---|---|---|---|")
        for entry in backend["parameters"]:
            role = ROLE_LABELS.get(entry.get("role", ""), entry.get("role", "—"))
            notes = entry.get("description") or entry.get("status") or ""
            add(
                f"| `{entry['name']}` | {role} | {_escape(_value_source(entry))} "
                f"| {_escape(notes)} |"
            )
        add("")

        add("### Scientific references")
        add("")
        for ref in backend["references"]:
            citation = _escape(ref["citation"])
            bibcode = ref.get("bibcode")
            add(f"- {citation}" + (f" (bibcode `{bibcode}`)" if bibcode else ""))
        add("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the on-disk document matches the registry; exit 1 if not",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DOC,
        help=f"output path (default: {DOC})",
    )
    args = parser.parse_args(argv)

    with open(REGISTRY, encoding="utf-8") as fh:
        reg = json.load(fh)
    rendered = render(reg)

    if args.check:
        if not args.output.exists():
            print(f"{args.output} does not exist; generate it first", file=sys.stderr)
            return 1
        current = args.output.read_text(encoding="utf-8")
        if current != rendered:
            print(
                f"{args.output} is out of date with the registry; "
                "run tools/generate_parameter_docs.py",
                file=sys.stderr,
            )
            return 1
        print(f"{args.output} is current")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
