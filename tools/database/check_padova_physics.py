"""Physics validation for the legacy Padova isochrone archives.

Per isochrone, on the native values exactly as read:

padova/2000 (isochron.dat; needs isochsum.dat only for phase, not here):
1. Surface-gravity closure: logg - (log Mact - 2 log R + log g_sun)
   spread, with logR implied by L and Teff (Stefan-Boltzmann); reports
   the median and the spread. The absolute offset absorbs the source's
   solar constants; only the spread is a consistency statement.
2. Mini non-decreasing along the row order (the IMF finite-difference
   requirement).
3. Mact <= Mini within the file's print precision (Mact is F6.4 against
   Mini's F10.8; rounding artifacts up to ~5e-5 Msun are known).
4. FLUM inverts back to Mini (Salpeter A=1): residual reported.

padova/1994 (tableN):
1. FLUM-inverted initial mass non-decreasing along the row order (the
   current-mass column is NOT, by construction — mass-loss transitions).
2. Current mass <= inverted initial mass (M, and Mwind where Mwind > 0),
   within print tolerance.
3. On windless rows the inverted initial mass should track the tabulated
   current mass closely while the star has not lost mass; the largest
   MS-regime deviation is reported as the inversion sanity line.

Usage: python check_padova_physics.py FILE [FILE ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stellariso.models.padova.backend import (  # noqa: E402
    MBOL_SUN_1994,
    invert_flum,
    read_padova,
)

LOG_G_SUN = 4.438  # log10(cm/s2)
LOG_TEFF_SUN = np.log10(5777.0)


def implied_log_radius(log_l: np.ndarray, log_teff: np.ndarray) -> np.ndarray:
    """log10(R/Rsun) from L and Teff (Stefan-Boltzmann, solar units)."""
    return 0.5 * log_l + 2.0 * (LOG_TEFF_SUN - log_teff)


def check_2000(path: str) -> int:
    s = read_padova(path)
    failures = 0
    print(f"== {Path(path).name} :: {s.identity.label} (isochron.dat layout)")
    print(f"   isochrones: {len(s)}, rows: {len(s.native.table)}")
    worst_act = 0.0
    worst_flum = 0.0
    for iso in s:
        mini = np.asarray(iso.native["Mini"], dtype=float)
        mact = np.asarray(iso.native["Mact"], dtype=float)
        log_l = np.asarray(iso.native["logL"], dtype=float)
        log_teff = np.asarray(iso.native["logTeff"], dtype=float)
        logg = np.asarray(iso.native["logg"], dtype=float)
        flum = np.asarray(iso.native["FLUM"], dtype=float)

        log_r = implied_log_radius(log_l, log_teff)
        closure = logg - (np.log10(mact) - 2 * log_r + LOG_G_SUN)
        spread_g = float(np.median(np.abs(closure - np.median(closure))))
        monotone = bool(np.all(np.diff(mini) >= -1e-12))
        over = float(np.max(mact - mini))
        worst_act = max(worst_act, over)
        residual = float(np.max(np.abs(mini - invert_flum(flum))))
        worst_flum = max(worst_flum, residual)

        ok_g = spread_g < 5e-2
        ok_m = monotone
        ok_a = over <= 1e-4
        failures += (not ok_g) + (not ok_m) + (not ok_a)
        print(
            f"   log_age={iso.selection['log_age']:5.2f} "
            f"feh={iso.selection['initial_feh']:+.3f} "
            f"ov={iso.selection['overshoot']:.0f}: g-closure spread={spread_g:.2e} "
            f"[{'ok' if ok_g else 'FAIL'}], Mini monotone="
            f"[{'ok' if ok_m else 'FAIL'}], max(Mact-Mini)={over:+.1e} "
            f"[{'ok' if ok_a else 'FAIL'}]"
        )
    print(
        f"   archive maxima: Mact-Mini {worst_act:+.2e} Msun, "
        f"FLUM inversion residual {worst_flum:.2e} Msun"
    )
    return failures


def check_1994(path: str) -> int:
    s = read_padova(path)
    failures = 0
    print(f"== {Path(path).name} :: {s.identity.label} ({s.native.metadata['table']}, "
          f"Z={s.native.metadata['initial_z']})")
    print(f"   isochrones: {len(s)}, rows: {len(s.native.table)}")
    worst_over = 0.0
    worst_ms = 0.0
    for iso in s:
        m = np.asarray(iso.native["M"], dtype=float)
        mwind = np.asarray(iso.native["Mwind"], dtype=float)
        log_teff = np.asarray(iso.native["log(Teff)"], dtype=float)
        flum = np.asarray(iso.native["FLUM"], dtype=float)
        mini = invert_flum(flum)

        monotone = bool(np.all(np.diff(mini) >= -1e-12))
        current = np.where(mwind > 0, mwind, m)
        over = float(np.max(current - mini))
        worst_over = max(worst_over, over)
        # main-sequence dwarfs (windless, sub-solar luminosity): the star
        # has not lost mass, so the inversion must track the tabulated
        # current mass — the F11.8 print precision bounds the agreement
        mbol = np.asarray(iso.native["Mbol"], dtype=float)
        log_l = (MBOL_SUN_1994 - mbol) / 2.5
        ms = (mwind == 0) & (log_l < 0.5)
        ms_dev = float(np.max(np.abs(mini[ms] - m[ms]))) if ms.any() else 0.0
        worst_ms = max(worst_ms, ms_dev)

        ok_m = monotone
        ok_a = over <= 1e-3  # F7.4 mass column against F11.8 FLUM
        failures += (not ok_m) + (not ok_a)
        print(
            f"   log_age={iso.selection['log_age']:5.2f}: Mini monotone="
            f"[{'ok' if ok_m else 'FAIL'}], max(Mcur-Mini)={over:+.1e} "
            f"[{'ok' if ok_a else 'FAIL'}], MS inversion dev={ms_dev:.1e}"
        )
    print(
        f"   archive maxima: Mcur-Mini {worst_over:+.2e} Msun, "
        f"MS inversion deviation {worst_ms:.2e} Msun (zero point Mbol_sun="
        f"{MBOL_SUN_1994})"
    )
    return failures


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    total = 0
    for path in argv[1:]:
        s = read_padova(path)  # layout dispatch through the backend
        release = s.identity.release
        total += (check_2000 if release == "2000" else check_1994)(path)
    print("FAILURES:", total)
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
