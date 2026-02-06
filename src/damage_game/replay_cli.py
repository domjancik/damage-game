from __future__ import annotations

import argparse
import json
import os
import time

from .replay import list_game_logs, load_events, tail_events


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay Damage simulation logs")
    parser.add_argument("--log-dir", default=os.getenv("DAMAGE_LOG_DIR", "runs"))
    parser.add_argument("--game-id", help="Game id (for example game_20260206T093854Z)")
    parser.add_argument("--list", action="store_true", help="List available game logs")
    parser.add_argument("--tail", action="store_true", help="Tail game events in real time")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed multiplier when printing events")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.list or not args.game_id:
        logs = list_game_logs(args.log_dir)
        if not logs:
            print("No game logs found.")
            return
        for item in logs:
            print(f"{item.game_id} events={item.event_count} mtime={item.modified_ts:.0f}")
        if not args.game_id:
            return

    if args.tail:
        for event in tail_events(args.log_dir, args.game_id):
            print(json.dumps(event, ensure_ascii=True))
        return

    events = load_events(args.log_dir, args.game_id)
    delay = 0.4 / max(0.05, args.speed)
    for event in events:
        print(json.dumps(event, ensure_ascii=True))
        time.sleep(delay)


if __name__ == "__main__":
    main()
