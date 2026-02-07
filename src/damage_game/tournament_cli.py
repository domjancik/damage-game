from __future__ import annotations

import argparse
import os
import sys

from .profiles import apply_profile_overrides, list_profiles, load_profile
from .tournament import TournamentConfig, TournamentRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Damage tournament")
    parser.add_argument("--base-url", default=os.getenv("DAMAGE_BASE_URL", "http://localhost:1234/v1"))
    parser.add_argument("--model", default=os.getenv("DAMAGE_MODEL", "qwen2.5-14b-instruct-mlx"))
    parser.add_argument(
        "--fallback-models",
        default=os.getenv("DAMAGE_FALLBACK_MODELS", "mistral-small-3.2-24b-instruct-2506-mlx"),
        help="Comma-separated fallback model IDs",
    )
    parser.add_argument(
        "--player-models",
        default=os.getenv("DAMAGE_PLAYER_MODELS", ""),
        help="Comma-separated entrant model map, e.g. E1=modelA,E2=modelB",
    )
    parser.add_argument("--api-key", default=os.getenv("DAMAGE_API_KEY"))
    parser.add_argument("--entrants", type=int, default=int(os.getenv("DAMAGE_TOURNAMENT_ENTRANTS", "16")))
    parser.add_argument("--seat-format", type=int, default=int(os.getenv("DAMAGE_TOURNAMENT_SEAT_FORMAT", "6")))
    parser.add_argument("--turns", type=int, default=int(os.getenv("DAMAGE_TOURNAMENT_TURNS", "3")))
    parser.add_argument("--advance-per-table", type=int, default=int(os.getenv("DAMAGE_ADVANCE_PER_TABLE", "1")))
    parser.add_argument("--stakes-multiplier", type=float, default=float(os.getenv("DAMAGE_STAKES_MULTIPLIER", "1.5")))
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
        "--blinds",
        dest="enable_blinds",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ENABLE_BLINDS", False),
        help="Enable blinds for Texas Hold'em style hands",
    )
    parser.add_argument("--small-blind", type=int, default=int(os.getenv("DAMAGE_SMALL_BLIND", "5")))
    parser.add_argument("--big-blind", type=int, default=int(os.getenv("DAMAGE_BIG_BLIND", "10")))
    parser.add_argument(
        "--continue-until-survivors",
        type=int,
        default=int(os.getenv("DAMAGE_CONTINUE_UNTIL_SURVIVORS", "0")),
        help="If >0, continue each table game until this many active survivors remain (subject to --turns cap)",
    )
    parser.add_argument(
        "--eliminate-on-bankroll-zero",
        dest="eliminate_on_bankroll_zero",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ELIMINATE_ON_BANKROLL_ZERO", False),
        help="Treat bankroll <= 0 as elimination condition",
    )
    parser.add_argument(
        "--ongoing-table",
        dest="ongoing_table",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("DAMAGE_ONGOING_TABLE", False),
        help="Refill empty seats with newly joined players before each hand",
    )
    parser.add_argument(
        "--card-style",
        default=os.getenv("DAMAGE_CARD_STYLE", "draw5"),
        choices=["draw5", "holdem"],
        help="Card style: 5-card draw or Texas Hold'em style",
    )
    parser.add_argument("--context-window", type=int, default=8192)
    parser.add_argument("--log-dir", default=os.getenv("DAMAGE_LOG_DIR", "runs"))
    parser.add_argument("--profile", default=os.getenv("DAMAGE_PROFILE", "damage-game"), choices=list_profiles())
    parser.add_argument(
        "--profile-file",
        default=os.getenv("DAMAGE_PROFILE_FILE", ""),
        help="Optional JSON profile file to extend/override profile fields",
    )
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
            "enable_blinds": ["--blinds", "--no-blinds"],
            "small_blind": ["--small-blind"],
            "big_blind": ["--big-blind"],
            "continue_until_survivors": ["--continue-until-survivors"],
            "eliminate_on_bankroll_zero": ["--eliminate-on-bankroll-zero", "--no-eliminate-on-bankroll-zero"],
            "ongoing_table": ["--ongoing-table", "--no-ongoing-table"],
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

    runner = TournamentRunner(
        TournamentConfig(
            base_url=args.base_url,
            model=args.model,
            fallback_models=fallback_models,
            player_models=player_models,
            api_key=args.api_key,
            entrants=args.entrants,
            seat_format=args.seat_format,
            turns_per_game=args.turns,
            advance_per_table=args.advance_per_table,
            stakes_multiplier=args.stakes_multiplier,
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
            enable_blinds=args.enable_blinds,
            small_blind=max(0, int(args.small_blind)),
            big_blind=max(0, int(args.big_blind)),
            continue_until_survivors=max(0, int(args.continue_until_survivors)),
            eliminate_on_bankroll_zero=args.eliminate_on_bankroll_zero,
            ongoing_table=args.ongoing_table,
            model_context_window=args.context_window,
            log_dir=args.log_dir,
        )
    )
    out = runner.run()
    print(f"tournament_id={out['tournament_id']} champion={out['champion_player_id']}")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
