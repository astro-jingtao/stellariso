"""Physics validation for MIST theoretical isochrone files.

Checks (per isochrone block, on the native values exactly as read):

1. Stefan-Boltzmann closure: log_L - (4 log_Teff + 2 log_R) must be
   constant across the block (its absolute value absorbs the solar
   normalisation); reports median and spread.
2. Surface-gravity closure: log_g - (log M - 2 log R + log g_sun) spread.
3. initial_mass non-decreasing along EEP (ties allowed, as written by the
   interp form's 6-digit mass output).
4. Reimers anchor: for RGB rows (phase 2, |star_mdot| above noise,
   log_L > 2.5), the implied efficiency eta_R = |mdot| / (4e-13 L R / M);
   reports the median — MIST v1.2 is anchored near eta_R ~ 0.1.

Usage: python check_mist_physics.py FILE [FILE ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stellariso.models.mist.backend import read_mist  # noqa: E402

LOG_G_SUN = 4.438  # log10(27400 cm/s2), cgs


def check(path: str) -> int:
    s = read_mist(path)
    failures = 0
    print(f"== {Path(path).name} :: {s.identity.label}")
    print(f"   blocks: {len(s)}, ages: {s.keys()}, columns: {len(s.native.columns)}")
    for iso in s:
        log_age = iso.selection["log_age"]
        logL = iso.native["log_L"]
        logT = iso.native["log_Teff"]
        logR = iso.native["log_R"]
        logg = iso.native["log_g"]
        m = iso.native["initial_mass"]
        mdot = iso.native["star_mdot"]
        phase = iso.native["phase"]

        closure = logL - (4 * logT + 2 * logR)
        spread_l = np.median(np.abs(closure - np.median(closure)))
        grav = logg - (np.log10(m) - 2 * logR + LOG_G_SUN)
        spread_g = np.median(np.abs(grav - np.median(grav)))
        monotone = np.all(np.diff(m) >= -1e-12)

        rgb = (phase == 2) & (np.abs(mdot) > 1e-13) & (logL > 2.5)
        if rgb.any():
            eta = (-mdot[rgb]) / (4e-13 * 10.0**logL[rgb] * 10.0**logR[rgb] / m[rgb])
            eta_med = float(np.median(eta))
        else:
            eta_med = float("nan")

        ok_l = spread_l < 1e-3
        ok_g = spread_g < 5e-2
        ok_m = monotone
        failures += (not ok_l) + (not ok_g) + (not ok_m)
        print(
            f"   log_age={log_age:5.2f}: L-closure spread={spread_l:.2e} "
            f"[{'ok' if ok_l else 'FAIL'}], g-closure spread={spread_g:.2e} "
            f"[{'ok' if ok_g else 'FAIL'}], mass monotone="
            f"[{'ok' if ok_m else 'FAIL'}], eta_R median={eta_med:.3f}"
        )
    return failures


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    total = 0
    for path in argv[1:]:
        total += check(path)
    print("FAILURES:", total)
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
