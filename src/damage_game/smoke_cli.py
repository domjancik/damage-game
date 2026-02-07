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
    parser.add_argument(
        "--pick-models",
        action="store_true",
        help="Interactive TUI-like model picker for primary + fallback models before run",
    )
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        help="Override one config field: key=value (repeatable). Supports JSON literals and dot paths.",
    )
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


def _parse_override_value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        low = text.lower()
        if low in {"true", "false"}:
            return low == "true"
        if low in {"null", "none"}:
            return None
        try:
            return int(text)
        except Exception:
            pass
        try:
            return float(text)
        except Exception:
            return text


def _set_nested(cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = [p.strip() for p in dotted_key.split(".") if p.strip()]
    if not parts:
        return
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _apply_overrides(cfg: dict[str, Any], overrides: list[str]) -> dict[str, Any]:
    out = dict(cfg)
    for item in overrides:
        text = str(item or "").strip()
        if not text or "=" not in text:
            continue
        key, raw_val = text.split("=", 1)
        key = key.strip()
        if not key:
            continue
        _set_nested(out, key, _parse_override_value(raw_val))
    return out


def _pick_models_interactive(cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = str(cfg.get("base_url", "http://localhost:1234/v1"))
    current_model = str(cfg.get("model", "")).strip()
    api_key = cfg.get("api_key")
    client = OpenAICompatibleClient(OpenAICompatibleConfig(base_url=base_url, model=current_model, api_key=api_key))
    models = client.list_models()
    if not models:
        print("No models available from endpoint; keeping configured model values.")
        return cfg

    print("\nAvailable models:")
    for i, model in enumerate(models, start=1):
        marker = " (current)" if model == current_model else ""
        print(f"{i:>2}. {model}{marker}")

    def _idx(prompt: str, default: int) -> int:
        raw = input(prompt).strip()
        if not raw:
            return default
        try:
            i = int(raw)
        except Exception:
            return default
        if i < 1 or i > len(models):
            return default
        return i

    default_primary = models.index(current_model) + 1 if current_model in models else 1
    primary_idx = _idx(f"\nPrimary model [default {default_primary}]: ", default_primary)
    primary_model = models[primary_idx - 1]

    print("Fallback models: enter comma-separated numbers, empty for none.")
    fallback_raw = input("Fallback selections: ").strip()
    fallback_models: list[str] = []
    if fallback_raw:
        seen: set[str] = set()
        for token in fallback_raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                i = int(token)
            except Exception:
                continue
            if i < 1 or i > len(models):
                continue
            model = models[i - 1]
            if model == primary_model:
                continue
            if model in seen:
                continue
            seen.add(model)
            fallback_models.append(model)

    out = dict(cfg)
    out["model"] = primary_model
    out["fallback_models"] = fallback_models
    print(f"Selected primary={primary_model}")
    if fallback_models:
        print(f"Selected fallback={','.join(fallback_models)}")
    else:
        print("Selected fallback=<none>")
    return out


def main() -> None:
    args = _parser().parse_args()
    raw = _load_json(Path(args.config))
    cfg = _normalize_common(_apply_overrides(_merge_profile(raw), list(args.overrides or [])))
    if args.pick_models:
        cfg = _pick_models_interactive(cfg)
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
