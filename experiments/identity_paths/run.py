"""Run a separately frozen fit or evaluate its fixed nominations."""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.identity_paths.evaluate import run as evaluate
from experiments.identity_paths.fit import run as fit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "evaluate"))
    parser.add_argument(
        "--directory", type=Path, default=Path("generated/core-discovery/data")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "fit":
        fit(args.directory, args.output)
    else:
        evaluate(args.output)


if __name__ == "__main__":
    main()
