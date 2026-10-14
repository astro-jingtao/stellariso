"""Build the synthetic multi-block CMD 3.9 grid fixture.

Derives ``output_grid.dat`` from the REAL single-block capture
``output_table.dat`` (taken 2026-10-14): the header block and the data
rows are reused verbatim, except that the per-block keying columns
(``Zini``, ``MH``, ``logAge``) are rewritten so the file holds THREE
isochrone blocks — (logAge 9.0, Z 0.0152), (logAge 9.5, Z 0.0152),
(logAge 9.0, Z 0.0001) — each introduced by the repeated column-name
comment line, with the trailing ``#isochrone terminated`` marker.

Every other column (including Y, which is a current-surface quantity) is
carried over unchanged from the Z = 0.0152 source rows: the fixture
exercises the FORMAT (block structure, per-row keying columns, dispatch),
not the physics of the alternative compositions. MH is recomputed as
log10(Z / 0.014711), the form's own [M/H] zero point.

Run:  python make_cmd39_grid_fixture.py   (writes output_grid.dat)
"""

from __future__ import annotations

import math
from pathlib import Path

HERE = Path(__file__).parent

Z_SUN_MH = 0.014711  # the CMD form's [M/H] = 0 metallicity

SOURCE = HERE / "output_table.dat"
TARGET = HERE / "output_grid.dat"

BLOCKS = [
    {"logAge": "9.00000", "Zini": "0.0152"},
    {"logAge": "9.50000", "Zini": "0.0152"},
    {"logAge": "9.00000", "Zini": "0.0001"},
]


def main() -> None:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()

    header: list[str] = []
    column_line: str | None = None
    rows: list[list[str]] = []
    for line in lines:
        if line.startswith("#"):
            tokens = line.lstrip("#").split()
            if column_line is None and "Zini" in tokens and "Mini" in tokens:
                column_line = line
            elif column_line is None:
                header.append(line)
            # the source's trailing '#isochrone terminated' is dropped here
        elif line.strip():
            rows.append(line.split())
    assert column_line is not None and rows, "unexpected source shape"

    columns = column_line.lstrip("#").split()
    z_i, mh_i, age_i = columns.index("Zini"), columns.index("MH"), columns.index("logAge")

    out = list(header)
    for spec in BLOCKS:
        z = float(spec["Zini"])
        mh = math.log10(z / Z_SUN_MH)
        out.append(column_line)
        for row in rows:
            row = list(row)
            row[z_i] = spec["Zini"]
            row[mh_i] = f"{mh:.5f}"
            row[age_i] = spec["logAge"]
            out.append(" ".join(row))
    out.append("#isochrone terminated")

    TARGET.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {TARGET} ({len(BLOCKS)} blocks x {len(rows)} rows)")


if __name__ == "__main__":
    main()
