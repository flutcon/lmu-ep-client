from __future__ import annotations

import argparse
import logging
from pathlib import Path

from lmu_ep_client.poller import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lmu-ep-client",
        description="LMU Endurance Protocol Client — stint activity logger",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        type=Path,
        default=None,
        help="Directory to write session JSON files (default: ./sessions/)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    run(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
