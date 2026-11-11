"""Build the trimmed padova fixtures from the original VizieR files.

The originals are the two CDS/VizieR directories (J/A+AS/106/275 and
J/A+AS/141/371) fetched from the ADAC mirror's native tree
(http://vizier.nao.ac.jp/ftp/cats/J/A+AS/106/275,
.../J/A+AS/141/371); see README.md in this directory for the exact
URLs, sizes, and sha256 values.

Selection (rows are kept verbatim — no value is altered; only whole
isochrones are chosen, and within them every row is kept, so the
characteristic-point anchors and the shape features the phase rules
read stay intact):

- p2000/isochron.dat + isochsum.dat: five isochrones — (Overshoot=1,
  Z=0.019, log(age)=9.00), (1, 0.019, 10.00), (0, 0.019, 9.00),
  (1, 0.004, 9.00), and (1, 0.019, 7.80); the summary file keeps the
  characteristic-point rows of exactly those five.
- p1994/table5 (Z=0.02): blocks log(age) = 7.00 (young, Mwind rows),
  9.00 (one mass jump), 10.00 (two mass jumps, post-AGB/WD tail).
- p1994/table1 (Z=0.0004): block log(age) = 9.50 (two jumps at the
  lowest metallicity).

Usage: python make_padova_fixtures.py <downloaded-dir> <tests-data-dir>
with <downloaded-dir> holding the seven original .gz files + two
ReadMe files under j106275/ and j141371/ subdirectories.
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path


def read_lines(path: Path) -> list[str]:
    with gzip.open(path, "rt", encoding="ascii") as fh:
        return fh.read().splitlines()


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def keep_p2000(src: Path, out: Path) -> None:
    wanted = {
        ("1", "0.01900", " 9.00"),
        ("1", "0.01900", "10.00"),
        ("0", "0.01900", " 9.00"),
        ("1", "0.00400", " 9.00"),
        ("1", "0.01900", " 7.80"),
    }
    kept_iso = []
    kept_sum = []
    for line in read_lines(src / "j141371" / "isochron.dat.gz"):
        if not line.strip():
            continue
        key = (line[0], line[2:9], line[20:25])
        if key in wanted:
            kept_iso.append(line)
    for line in read_lines(src / "j141371" / "isochsum.dat.gz"):
        if not line.strip():
            continue
        key = (line[0], line[2:9], line[20:25])
        if key in wanted:
            kept_sum.append(line)
    n_keys = len({(l[0], l[2:9], l[20:25]) for l in kept_iso})
    if n_keys != len(wanted):
        raise SystemExit(
            f"expected {len(wanted)} isochrones in isochron.dat, found {n_keys}"
        )
    n_sum = len({(l[0], l[2:9], l[20:25]) for l in kept_sum})
    if n_sum != len(wanted):
        raise SystemExit(
            f"expected {len(wanted)} summary isochrones, found {n_sum}"
        )
    write_lines(out / "p2000" / "isochron.dat", kept_iso)
    write_lines(out / "p2000" / "isochsum.dat", kept_sum)


def keep_p94(src: Path, out: Path, table: str, ages: set[float]) -> None:
    kept = [
        line
        for line in read_lines(src / "j106275" / f"{table}.gz")
        if line.strip() and round(float(line[2:8]), 3) in ages
    ]
    found = {round(float(l[2:8]), 3) for l in kept}
    if found != ages:
        raise SystemExit(f"{table}: expected blocks {sorted(ages)}, found {sorted(found)}")
    write_lines(out / "p1994" / table, kept)


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        raise SystemExit(__doc__)
    src, out = Path(argv[1]), Path(argv[2])
    keep_p2000(src, out)
    keep_p94(src, out, "table5", {6.70, 7.00, 9.00, 10.00})
    keep_p94(src, out, "table1", {9.50})
    print(f"wrote fixtures under {out}/p2000 and {out}/p1994")


if __name__ == "__main__":
    main(sys.argv)
