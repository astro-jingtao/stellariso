"""Fetch PARSEC isochrones from the Padova CMD web form.

Submits the CMD 3.9 form (https://stev.oapd.inaf.it/cgi-bin/cmd) with the
complete field-set protocol (stellariso.models.parsec.cmd_form) and saves
the server-computed isochrone table together with a sidecar .record.json
stating the exact request payload, the CMD version, the job timestamps,
the output checksum, and the server's own header echo (the PARSEC + COLIBRI
release chain and the physics switches) — everything needed to reproduce
and cite the table.

Flags map one-to-one onto the form's own field names (the wire vocabulary);
values default to the verified browser baseline (PARSEC v1.2S +
COLIBRI S_LMC_08_web, UBVRIJHK YBC Vega magnitudes, isochrone tables):

    python tools/fetch_parsec_isochrones.py \
        --isoc_isagelog 1 --isoc_lagelow 9.0 --isoc_lageupp 10.0 --isoc_dlage 0.5 \
        --isoc_ismetlog 1 --isoc_metlow -1 --isoc_metupp 0 --isoc_dmet 1 \
        [--out my_isos.dat]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stellariso.models.parsec.cmd_form import (
    DEFAULT_FIELDS,
    CmdFieldSet,
    CmdFormClient,
)

#: fields a CLI flag may override (everything the form defines, plus the
#: optional gzip checkbox)
_FLAGGED = tuple(DEFAULT_FIELDS) + ("output_gzip",)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for name in _FLAGGED:
        parser.add_argument(f"--{name}", default=None, help=DEFAULT_FIELDS[name])
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output table path (default: cmd_<output_name>.dat); the record "
        "is written next to it as <out>.record.json",
    )
    args = parser.parse_args(argv)

    overrides = {name: getattr(args, name) for name in _FLAGGED}
    overrides = {name: value for name, value in overrides.items() if value is not None}
    fields = CmdFieldSet.from_overrides(**overrides)

    client = CmdFormClient()
    job = client.submit(fields)
    print(f"job submitted {job.submitted_at}, completed {job.completed_at}")
    print(f"output: {job.output_url} (server keeps it {job.retention_note})")
    out = client.fetch_output(job)
    print(f"{out.n_data_rows} data rows, sha256 {out.sha256}")

    target = args.out or Path(out.filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out.content)
    record_path = target.with_name(target.name + ".record.json")
    record_path.write_text(
        json.dumps(out.record(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {target} and {record_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
