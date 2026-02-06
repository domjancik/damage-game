from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class EventLogger:
    game_id: str
    events_path: Path

    @classmethod
    def create(cls, log_dir: str, game_id: str) -> "EventLogger":
        root = Path(log_dir)
        root.mkdir(parents=True, exist_ok=True)
        events_path = root / f"{game_id}.events.jsonl"
        return cls(game_id=game_id, events_path=events_path)

    def write(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "schema_version": "0.1",
            "type": event_type,
            "game_id": self.game_id,
            "ts": utc_now_iso(),
            "payload": payload,
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")

