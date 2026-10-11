"""Synthesize PARSEC isochrones locally from the official v1.2S tracks.

PARSEC publishes isochrones only through the CMD web form (opaque,
unscriptable); this script builds them transparently from the official
track archives instead: each track is interpolated linearly in age at the
requested ages, one isochrone point per initial mass, no cross-track
interpolation or extrapolation. Every output block states the exact
transformation; read it back with stellariso (parse each block as a table
or re-synthesize in-process with stellariso.synthesize_isochrones).

    python tools/synthesize_parsec_isochrones.py Z0.0001Y0.249.zip \
        --log-ages 8.0,8.5,9.0,9.5,10.0 [--out my_isos.dat]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from stellariso.models.parsec.tracks import parse_parsec_tracks
from stellariso.synthesis import synthesize_isochrones
from stellariso.warnings import SynthesizedProductWarning

COLUMNS = (
    "initial_mass current_mass log_luminosity log_effective_temperature "
    "log_radius log_surface_gravity he_core_mass co_core_mass native_phase "
    "phase"
).split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tracks",
        type=Path,
        help="PARSEC v1.2S track zip (as downloaded) or extracted directory",
    )
    parser.add_argument(
        "--log-ages",
        required=True,
        help="comma-separated log10(age/yr) values, e.g. 9.0,9.5,10.0",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output table path (default: <input stem>_synthesized_isochrones.dat)",
    )
    args = parser.parse_args(argv)

    ages = [float(a) for a in args.log_ages.split(",")]
    if not ages:
        parser.error("--log-ages must contain at least one value")

    track_set = parse_parsec_tracks(args.tracks)
    print(
        f"tracks: {len(track_set)} standard, {len(track_set.hb_tracks)} HB, "
        f"{len(track_set.discarded)} ADD discarded; "
        f"Z={track_set.initial_z} Y={track_set.initial_helium}"
    )

    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        isochrones = synthesize_isochrones(track_set, ages)
    n_synth_warnings = sum(
        1 for w in caught if issubclass(w.category, SynthesizedProductWarning)
    )
    print(f"synthesized {len(isochrones)} isochrone(s) ({n_synth_warnings} notice(s))")

    out = args.out or args.tracks.with_name(
        args.tracks.stem + "_synthesized_isochrones.dat"
    )
    lines = [
        "# PARSEC v1.2S isochrones synthesized locally by stellariso",
        f"# source tracks: {args.tracks}",
        f"# composition: Z={track_set.initial_z} Y={track_set.initial_helium}",
        "# method: linear interpolation in age within each track; "
        "no cross-track interpolation, no extrapolation",
        "# NOT a model-team isochrone product (the CMD web form is not used)",
    ]
    for iso in isochrones:
        lines.append("")
        lines.append(f"# log_age = {iso.selection['log_age']:g}")
        lines.append("# " + " ".join(COLUMNS))
        table = iso.native.to_table()
        for row in table:
            values = []
            for name in COLUMNS:
                v = row[name]
                values.append(f"{v:.10g}" if not isinstance(v, str) else v)
            lines.append("  ".join(values))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out}")

    for iso in isochrones:
        omitted = iso.native.metadata.get("omitted", [])
        if omitted:
            print(
                f"  log_age {iso.selection['log_age']:g}: "
                f"{len(iso)} rows, {len(omitted)} track(s) omitted"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
