from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "damage-game": {
        "card_style": "draw5",
        "enable_lives": True,
        "enable_direct_emoter_attacks": True,
        "enable_discussion_layer": True,
        "enable_offturn_self_regulate": True,
        "enable_offturn_chatter": True,
        "enable_blinds": False,
        "ongoing_table": False,
        "ante": 10,
        "min_raise": 10,
        "starting_bankroll": 200,
    },
    "poker-texasholdem": {
        "card_style": "holdem",
        "enable_lives": False,
        "enable_direct_emoter_attacks": False,
        "enable_discussion_layer": True,
        "enable_offturn_self_regulate": False,
        "enable_offturn_chatter": False,
        "enable_blinds": True,
        "ongoing_table": False,
        "small_blind": 5,
        "big_blind": 10,
        "ante": 0,
        "min_raise": 10,
        "starting_bankroll": 300,
    },
}


def list_profiles() -> list[str]:
    return sorted(BUILTIN_PROFILES.keys())


def load_profile(profile_name: str | None, profile_file: str | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if profile_name:
        merged.update(BUILTIN_PROFILES.get(profile_name.strip().lower(), {}))
    if profile_file:
        path = Path(profile_file)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if isinstance(data, dict):
                merged.update(data)
    return merged


def apply_profile_overrides(args: Any, profile: dict[str, Any], arg_to_flags: dict[str, list[str]], argv: list[str]) -> None:
    for field, value in profile.items():
        if not hasattr(args, field):
            continue
        flags = arg_to_flags.get(field, [])
        if any(flag in argv for flag in flags):
            continue
        setattr(args, field, value)
