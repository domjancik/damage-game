from __future__ import annotations

import argparse
import os
import sys

from .provider_openai_compat import OpenAICompatibleClient, OpenAICompatibleConfig
from .profiles import apply_profile_overrides, list_profiles, load_profile
from .simulator import DamageSimulator, SimulatorConfig


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Damage simulation")
    parser.add_argument("--base-url", default=os.getenv("DAMAGE_BASE_URL", "http://localhost:1234/v1"))
    parser.add_argument("--model", default=os.getenv("DAMAGE_MODEL", "qwen2.5-14b-instruct-mlx"))
    parser.add_argument(
        "--fallback-models",
        default=os.getenv("DAMAGE_FALLBACK_MODELS", "mistral-small-3.2-24b-instruct-2506-mlx"),
        help="Comma-separated fallback model IDs used by the router",
    )
    parser.add_argument(
        "--player-models",
        default=os.getenv("DAMAGE_PLAYER_MODELS", ""),
        help="Comma-separated per-player model map, e.g. P1=modelA,P2=modelB",
    )
    parser.add_argument("--api-key", default=os.getenv("DAMAGE_API_KEY"))
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--seed", type=int, default=int(os.getenv("DAMAGE_SEED", "42")))
    parser.add_argument("--ante", type=int, default=int(os.getenv("DAMAGE_ANTE", "10")))
    parser.add_argument("--min-raise", type=int, default=int(os.getenv("DAMAGE_MIN_RAISE", "10")))
    parser.add_argument("--starting-bankroll", type=int, default=int(os.getenv("DAMAGE_STARTING_BANKROLL", "200")))
    parser.add_argument(
        "--lives",
        dest="enable_lives",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ENABLE_LIVES", True),
        help="Enable life-loss elimination rule",
    )
    parser.add_argument(
        "--direct-emoter-attacks",
        dest="enable_direct_emoter_attacks",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ENABLE_DIRECT_EMOTER_ATTACKS", True),
        help="Enable direct emotional effects on successful raises",
    )
    parser.add_argument(
        "--discussion-layer",
        dest="enable_discussion_layer",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ENABLE_DISCUSSION_LAYER", False),
        help="Enable chatter phase where players attempt discussion-based emotion effects",
    )
    parser.add_argument(
        "--offturn-regulate",
        dest="enable_offturn_self_regulate",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ENABLE_OFFTURN_REGULATE", False),
        help="Allow players to self-regulate on other players' turns",
    )
    parser.add_argument(
        "--offturn-chat",
        dest="enable_offturn_chatter",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ENABLE_OFFTURN_CHAT", False),
        help="Allow players to chatter on other players' turns",
    )
    parser.add_argument(
        "--card-style",
        default=os.getenv("DAMAGE_CARD_STYLE", "draw5"),
        choices=["draw5", "holdem"],
        help="Card style: 5-card draw or Texas Hold'em style (2 hole + 5 community)",
    )
    parser.add_argument("--context-window", type=int, default=8192)
    parser.add_argument("--log-dir", default=os.getenv("DAMAGE_LOG_DIR", "runs"))
    parser.add_argument("--profile", default=os.getenv("DAMAGE_PROFILE", "damage-game"), choices=list_profiles())
    parser.add_argument(
        "--profile-file",
        default=os.getenv("DAMAGE_PROFILE_FILE", ""),
        help="Optional JSON profile file to extend/override profile fields",
    )
    parser.add_argument("--probe", action="store_true", help="Only probe model connectivity")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    profile = load_profile(args.profile, args.profile_file or None)
    apply_profile_overrides(
        args,
        profile,
        {
            "card_style": ["--card-style"],
            "ante": ["--ante"],
            "min_raise": ["--min-raise"],
            "starting_bankroll": ["--starting-bankroll"],
            "enable_lives": ["--lives", "--no-lives"],
            "enable_direct_emoter_attacks": ["--direct-emoter-attacks", "--no-direct-emoter-attacks"],
            "enable_discussion_layer": ["--discussion-layer", "--no-discussion-layer"],
            "enable_offturn_self_regulate": ["--offturn-regulate", "--no-offturn-regulate"],
            "enable_offturn_chatter": ["--offturn-chat", "--no-offturn-chat"],
        },
        sys.argv[1:],
    )
    fallback_models = [m.strip() for m in args.fallback_models.split(",") if m.strip()]
    player_models: dict[str, str] = {}
    if args.player_models.strip():
        for item in args.player_models.split(","):
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            k = k.strip().upper()
            v = v.strip()
            if k and v:
                player_models[k] = v

    if args.probe:
        client = OpenAICompatibleClient(
            OpenAICompatibleConfig(base_url=args.base_url, model=args.model, api_key=args.api_key)
        )
        models = client.list_models()
        print("Available models:")
        for model in models:
            print(f"- {model}")
        return

    sim = DamageSimulator(
        SimulatorConfig(
            base_url=args.base_url,
            model=args.model,
            fallback_models=fallback_models,
            player_models=player_models,
            api_key=args.api_key,
            players=args.players,
            turns=args.turns,
            seed=args.seed,
            ante=args.ante,
            min_raise=args.min_raise,
            starting_bankroll=args.starting_bankroll,
            card_style=args.card_style,
            enable_lives=args.enable_lives,
            enable_direct_emoter_attacks=args.enable_direct_emoter_attacks,
            enable_discussion_layer=args.enable_discussion_layer,
            enable_offturn_self_regulate=args.enable_offturn_self_regulate,
            enable_offturn_chatter=args.enable_offturn_chatter,
            model_context_window=args.context_window,
            log_dir=args.log_dir,
        )
    )
    sim.run()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
