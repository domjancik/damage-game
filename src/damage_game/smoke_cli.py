from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from .profiles import load_profile
from .provider_openai_compat import OpenAICompatibleClient, OpenAICompatibleConfig
from .simulator import DamageSimulator, SimulatorConfig
from .tournament import TournamentConfig, TournamentRunner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run config-driven smoke tests")
    parser.add_argument("--config", required=True, help="Path to smoke JSON config")
    parser.add_argument("--mode", choices=["sim", "tournament", "probe"], default="", help="Optional override mode")
    return parser


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    return data


def _merge_profile(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    profile_name = str(out.get("profile", "") or "").strip() or None
    profile_file = str(out.get("profile_file", "") or "").strip() or None
    profile = load_profile(profile_name, profile_file)
    for key, value in profile.items():
        out.setdefault(key, value)
    return out


def _pick_dataclass_fields(cls: type, src: dict[str, Any]) -> dict[str, Any]:
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in src.items() if k in allowed}


def _normalize_common(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    if "fallback_models" in out and isinstance(out["fallback_models"], str):
        out["fallback_models"] = [x.strip() for x in out["fallback_models"].split(",") if x.strip()]
    if "player_models" in out and isinstance(out["player_models"], str):
        parsed: dict[str, str] = {}
        for item in out["player_models"].split(","):
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            k = k.strip().upper()
            v = v.strip()
            if k and v:
                parsed[k] = v
        out["player_models"] = parsed
    return out


def main() -> None:
    args = _parser().parse_args()
    raw = _load_json(Path(args.config))
    cfg = _normalize_common(_merge_profile(raw))
    mode = (args.mode or str(cfg.get("mode", "sim"))).strip().lower()

    if mode == "probe":
        base_url = str(cfg.get("base_url", "http://localhost:1234/v1"))
        model = str(cfg.get("model", ""))
        api_key = cfg.get("api_key")
        client = OpenAICompatibleClient(OpenAICompatibleConfig(base_url=base_url, model=model, api_key=api_key))
        models = client.list_models()
        print("Available models:")
        for m in models:
            print(f"- {m}")
        return

    if mode == "tournament":
        tc = TournamentConfig(**_pick_dataclass_fields(TournamentConfig, cfg))
        out = TournamentRunner(tc).run()
        print(f"tournament_id={out['tournament_id']} champion={out['champion_player_id']}")
        return

    sc = SimulatorConfig(**_pick_dataclass_fields(SimulatorConfig, cfg))
    out = DamageSimulator(sc).run()
    print(f"game_id={out['game_id']} winners={','.join(out['winners']) or '-'}")


if __name__ == "__main__":
    main()
