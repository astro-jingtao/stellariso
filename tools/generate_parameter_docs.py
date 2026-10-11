"""Write docs/unified-parameters.md from the unified-parameter registry.

The registry is split by ownership: definitions in
src/stellariso/registry/unified_parameters.json, per-family
characteristics and mappings in
src/stellariso/models/<family>/unified_parameters.json. stellariso.registry
loads and validates them as one registry; this tool renders it (through
stellariso.registry.docs) into the human-readable reference document. Run
it after every registry edit:

    python tools/generate_parameter_docs.py           # write the doc
    python tools/generate_parameter_docs.py --check   # verify it is current
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stellariso.registry.docs import render_documentation

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "unified-parameters.md"


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

    rendered = render_documentation()

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
