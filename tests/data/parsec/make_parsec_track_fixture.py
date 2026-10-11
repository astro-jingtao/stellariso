"""Create the PARSEC v1.2S track fixture from a real official zip.

Usage: python make_parsec_track_fixture.py <path-to-Z0.0001Y0.249.zip>

The fixture keeps the zip's directory/file naming (so the composition and
initial masses still parse from the names) with a trimmed, deterministic
row selection: the first and last model of each track, every model where
the integer part of PHASE changes, and every 20th model in between. The
ADD merge file and one HB track are kept (trimmed) so the discard and
HB code paths are exercised against real data. See README.md here.
"""

from __future__ import annotations

import hashlib
import math
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
WANTED = {
    # note the OUTA prefix differs per mass range (overshoot parameter A);
    # names below are verbatim from the archive
    "Z0.0001Y0.249/Z0.0001Y0.249OUTA1.77_F7_M000.600.DAT",
    "Z0.0001Y0.249/Z0.0001Y0.249OUTA1.74_F7_M000.800.DAT",
    "Z0.0001Y0.249/Z0.0001Y0.249OUTA1.74_F7_M001.000.DAT",
    "Z0.0001Y0.249/Z0.0001Y0.249OUTA1.74_F7_M0.700.HB.DAT",
    "Z0.0001Y0.249/Z0.0001Y0.249OUTA1.74_F7_M060.000ADD.DAT",
}
KEEP_EVERY = 20


def trim(lines: list[str]) -> list[str]:
    header, data = lines[0], [l for l in lines[1:] if l.strip()]
    phase_col = header.split().index("PHASE")
    keep = set()
    keep.add(0)
    keep.add(len(data) - 1)
    last_int = None
    for i, line in enumerate(data):
        code = int(math.floor(float(line.split()[phase_col]) + 1e-9))
        if code != last_int:
            keep.add(i)
            last_int = code
        elif i % KEEP_EVERY == 0:
            keep.add(i)
    kept = [data[i] for i in sorted(keep)]
    return [header] + kept


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1])
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    zf = zipfile.ZipFile(src)
    out_root = HERE / "tracks_v1p2S_Z0.0001Y0.249_fixture"
    (out_root / "Z0.0001Y0.249").mkdir(parents=True, exist_ok=True)
    for name in WANTED:
        lines = zf.read(name).decode("ascii").splitlines()
        trimmed = trim(lines)
        out = out_root / name
        out.write_text("\n".join(trimmed) + "\n", encoding="ascii", newline="\n")
        print(f"{name}: {len(lines)} -> {len(trimmed)} rows")
    (out_root / "SOURCE.txt").write_text(
        f"source zip: {src.name}\n"
        f"source sha256: {sha}\n"
        "source url: "
        "https://stev.oapd.inaf.it/PARSEC/Database/PARSECv1.2/Z0.0001Y0.249.zip\n"
        "trimmed by make_parsec_track_fixture.py on 2026-10-11\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
