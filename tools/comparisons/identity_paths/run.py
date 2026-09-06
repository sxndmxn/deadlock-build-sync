"""Run a separately frozen fit or evaluate its fixed nominations."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.comparisons.build_guides.run import generate
from tools.comparisons.identity_paths.evaluate import run as evaluate
from tools.comparisons.identity_paths.fit import run as fit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "evaluate", "preview"))
    parser.add_argument(
        "--directory", type=Path, default=Path("generated/core-discovery/data")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview-output", type=Path)
    parser.add_argument("--heroes", type=int, nargs="+")
    args = parser.parse_args()
    if args.stage == "fit":
        fit(args.directory, args.output)
    elif args.stage == "evaluate":
        evaluate(args.output)
    elif args.preview_output is None:
        parser.error("preview requires --preview-output for the assembled guides")
    else:
        generate(args.output, args.preview_output, heroes=args.heroes)


if __name__ == "__main__":
    main()
