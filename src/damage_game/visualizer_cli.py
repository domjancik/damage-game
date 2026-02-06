from __future__ import annotations

import argparse
import os

from .visualizer_server import VisualizerServer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Damage web visualizer")
    parser.add_argument("--host", default=os.getenv("DAMAGE_VIZ_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DAMAGE_VIZ_PORT", "8787")))
    parser.add_argument("--log-dir", default=os.getenv("DAMAGE_LOG_DIR", "runs"))
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    VisualizerServer(host=args.host, port=args.port, log_dir=args.log_dir).run()


if __name__ == "__main__":
    main()

