from __future__ import annotations

import argparse
import os

from .provider_openai_compat import OpenAICompatibleClient, OpenAICompatibleConfig
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
    parser.add_argument("--api-key", default=os.getenv("DAMAGE_API_KEY"))
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--seed", type=int, default=int(os.getenv("DAMAGE_SEED", "42")))
    parser.add_argument("--ante", type=int, default=int(os.getenv("DAMAGE_ANTE", "10")))
    parser.add_argument("--min-raise", type=int, default=int(os.getenv("DAMAGE_MIN_RAISE", "10")))
    parser.add_argument("--starting-bankroll", type=int, default=int(os.getenv("DAMAGE_STARTING_BANKROLL", "200")))
    parser.add_argument("--context-window", type=int, default=8192)
    parser.add_argument("--log-dir", default=os.getenv("DAMAGE_LOG_DIR", "runs"))
    parser.add_argument("--probe", action="store_true", help="Only probe model connectivity")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    fallback_models = [m.strip() for m in args.fallback_models.split(",") if m.strip()]

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
            api_key=args.api_key,
            players=args.players,
            turns=args.turns,
            seed=args.seed,
            ante=args.ante,
            min_raise=args.min_raise,
            starting_bankroll=args.starting_bankroll,
            model_context_window=args.context_window,
            log_dir=args.log_dir,
        )
    )
    sim.run()


if __name__ == "__main__":
    main()
