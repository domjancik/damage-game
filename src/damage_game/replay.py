from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class GameLogInfo:
    game_id: str
    path: Path
    event_count: int
    modified_ts: float


def log_path(log_dir: str, game_id: str) -> Path:
    return Path(log_dir) / f"{game_id}.events.jsonl"


def bio_path(log_dir: str, game_id: str, player_id: str) -> Path:
    return Path(log_dir) / f"{game_id}.bios" / f"{player_id}.md"


def list_game_logs(log_dir: str) -> list[GameLogInfo]:
    return list_logs_with_prefix(log_dir, "game_")


def list_tournament_logs(log_dir: str) -> list[GameLogInfo]:
    return list_logs_with_prefix(log_dir, "tournament_")


def list_logs_with_prefix(log_dir: str, prefix: str) -> list[GameLogInfo]:
    root = Path(log_dir)
    if not root.exists():
        return []
    out: list[GameLogInfo] = []
    for path in root.glob("*.events.jsonl"):
        game_id = path.name.replace(".events.jsonl", "")
        if not game_id.startswith(prefix):
            continue
        event_count = 0
        with path.open("r", encoding="utf-8") as f:
            for _ in f:
                event_count += 1
        out.append(
            GameLogInfo(
                game_id=game_id,
                path=path,
                event_count=event_count,
                modified_ts=path.stat().st_mtime,
            )
        )
    out.sort(key=lambda x: x.modified_ts, reverse=True)
    return out


def load_events(log_dir: str, game_id: str) -> list[dict]:
    path = log_path(log_dir, game_id)
    if not path.exists():
        raise FileNotFoundError(f"log not found: {path}")
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def tail_events(log_dir: str, game_id: str, poll_interval_s: float = 0.4) -> Iterator[dict]:
    path = log_path(log_dir, game_id)
    if not path.exists():
        raise FileNotFoundError(f"log not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        while True:
            line = f.readline()
            if not line:
                time.sleep(poll_interval_s)
                continue
            line = line.strip()
            if line:
                yield json.loads(line)
