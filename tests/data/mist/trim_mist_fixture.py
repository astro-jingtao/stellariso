"""Regenerate the trimmed MIST test fixture from a full interp-form .iso.

The fixture keeps the file header verbatim and stride-samples each isochrone
block's data rows, rewriting each block's stated EEP count to match. The
result is format-equivalent to a real MIST theoretical-isochrone file with
the same header, column names, and block layout, but small enough to commit.

To regenerate:
1. Obtain the original file by POSTing to https://mist.science/iso_form.php
   with the fields recorded in README.md (same directory).
2. Run:  python trim_mist_fixture.py <original.iso> <fixture.iso> [max_rows]
"""

from __future__ import annotations

import sys
from pathlib import Path


def trim(src: Path, dst: Path, max_rows: int = 150) -> None:
    lines = src.read_text(encoding="ascii", errors="replace").splitlines()

    header: list[str] = []
    blocks: list[dict] = []
    i = 0
    # file header: everything up to the first 'number of EEPs' line
    while i < len(lines) and "number of EEPs" not in lines[i]:
        header.append(lines[i])
        i += 1
    while i < len(lines):
        assert lines[i].startswith("#") and "number of EEPs" in lines[i], lines[i]
        block_header = [lines[i], lines[i + 1], lines[i + 2]]
        i += 3
        data: list[str] = []
        while i < len(lines) and not lines[i].startswith("#"):
            if lines[i].strip():
                data.append(lines[i])
            i += 1
        blocks.append({"header": block_header, "data": data})

    out: list[str] = list(header)
    for block in blocks:
        data = block["data"]
        stride = max(1, -(-len(data) // max_rows))
        kept = data[::stride]
        # rewrite the stated EEP count in 'number of EEPs, cols =  N   C'
        first = block["header"][0]
        old_n, n_cols = first.split("=")[1].split()
        new_first = first.replace(f"=  {old_n} ", f"=  {len(kept)} ", 1)
        # single-pad form may differ; rebuild robustly
        if new_first == first:
            new_first = f"# number of EEPs, cols =  {len(kept)}   {n_cols}"
        out.append(new_first)
        out.extend(block["header"][1:])
        out.extend(kept)

    dst.write_text("\n".join(out) + "\n", encoding="ascii")
    print(f"wrote {dst}: {len(out)} lines from {len(lines)}")


if __name__ == "__main__":
    trim(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 150)
