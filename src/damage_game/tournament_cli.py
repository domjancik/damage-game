from __future__ import annotations

import argparse
import os

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
    parser.add_argument("--context-window", type=int, default=8192)
    parser.add_argument("--log-dir", default=os.getenv("DAMAGE_LOG_DIR", "runs"))
    return parser


def main() -> None:
    args = _build_parser().parse_args()
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
            model_context_window=args.context_window,
            log_dir=args.log_dir,
        )
    )
    out = runner.run()
    print(f"tournament_id={out['tournament_id']} champion={out['champion_player_id']}")


if __name__ == "__main__":
    main()
