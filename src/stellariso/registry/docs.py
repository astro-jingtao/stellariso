"""Render the unified-parameter registry into its documentation form.

``render_documentation()`` produces the markdown reference that ships as
``docs/unified-parameters.md`` (via ``tools/generate_parameter_docs.py``)
and is copied into every built database as a self-containment snapshot.
"""

from __future__ import annotations

from stellariso.registry import load_registry

__all__ = ["render_documentation"]

_ROLE_LABELS = {
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
        parts.append(
            f"relation `{entry['relation']}`" + (f" ({plist})" if plist else "")
        )
    if "when" in entry:
        parts.append(f"only when {entry['when']}")
    return "; ".join(parts) if parts else "—"


def _escape(text: str | None) -> str:
    if not text:
        return "—"
    return text.replace("|", "\\|").replace("\n", " ")


def render_documentation() -> str:
    reg = load_registry()
    lines: list[str] = []
    add = lines.append

    add("# Unified parameters and field mappings")
    add("")
    add(
        "This document records the unified vocabulary every data source maps "
        "into, each source's own fields and physical parameters, and the "
        "mapping between the two layers. It is generated from the registry "
        "data files: `src/stellariso/registry/unified_parameters.json` holds "
        "stellariso's own definitions (unified fields, coarse stages, "
        "physical parameters), and each family's characteristics and "
        "mappings live in `src/stellariso/models/<family>/"
        "unified_parameters.json` next to its `catalog.json`. The library "
        "code loads and validates them as one registry — the backends read "
        "their field specs, phase mappings, and static parameter knowledge "
        "from it."
    )
    add("")
    add("Regenerate the repository copy after editing the registry:")
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

    titles = {"mist": "MIST", "parsec": "PARSEC / Padova"}
    product_titles = {
        "isochrones": "Isochrone tables",
        "cmd_table": "CMD web-form isochrone tables",
    }
    for name, backend in reg["backends"].items():
        add(f"## {titles.get(name, name)} (`{name}`)")
        add("")
        add(f"Field mapping version: `{backend['mapping_version']}`.")
        add("")
        for note in backend["notes"]:
            add(f"- {note}")
        add("")

        for product_key, product in backend["products"].items():
            add(f"### {product_titles.get(product_key, product_key)} (`{product_key}`)")
            add("")
            for note in product.get("notes", []):
                add(f"- {note}")
            if product.get("notes"):
                add("")

            add("#### Field mappings")
            add("")
            add("| Unified field | Native source | Origin | Transformation | Notes |")
            add("|---|---|---|---|---|")
            for m in product["field_mappings"]:
                native = m.get("native")
                native_text = f"`{native}`" if native else "—"
                add(
                    f"| `{m['unified']}` | {native_text} | {m['origin']} "
                    f"| {_escape(m.get('transformation'))} "
                    f"| {_escape(m.get('description'))} |"
                )
            add("")

            for pm_key, pm_title in (
                ("phase_mapping", "Phase mapping"),
                ("hb_phase_mapping", "Phase mapping — HB track files"),
            ):
                if pm_key not in product:
                    continue
                add(f"#### {pm_title}")
                add("")
                add("| Native code | Meaning | Unified stage |")
                add("|---|---|---|")
                meaning_key = pm_key.replace("phase_mapping", "phase_code_meanings")
                meanings = product.get(meaning_key, {})
                for code, stage in product[pm_key].items():
                    add(f"| {code} | {_escape(meanings.get(code))} | `{stage}` |")
                add("")

            if "eep_anchors" in product:
                add("#### Primary EEP anchors")
                add("")
                add("| Anchor | EEP number |")
                add("|---|---|")
                for anchor, eep in product["eep_anchors"].items():
                    add(f"| {anchor} | {eep} |")
                add("")

            add("#### Physical parameters")
            add("")
            add("| Parameter | Role | Value / source | Notes |")
            add("|---|---|---|---|")
            for entry in product["parameters"]:
                role = _ROLE_LABELS.get(entry.get("role", ""), entry.get("role", "—"))
                notes = entry.get("description") or entry.get("status") or ""
                add(
                    f"| `{entry['name']}` | {role} "
                    f"| {_escape(_value_source(entry))} | {_escape(notes)} |"
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
