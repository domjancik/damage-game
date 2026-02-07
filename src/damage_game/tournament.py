from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .event_log import EventLogger
from .simulator import DamageSimulator, SimulatorConfig


@dataclass(slots=True)
class TournamentConfig:
    base_url: str
    model: str
    api_key: str | None = None
    fallback_models: list[str] | None = None
    player_models: dict[str, str] | None = None
    entrants: int = 16
    seat_format: int = 6
    turns_per_game: int = 3
    seed: int = 42
    ante: int = 10
    min_raise: int = 10
    starting_bankroll: int = 200
    card_style: str = "draw5"
    enable_lives: bool = True
    enable_direct_emoter_attacks: bool = True
    enable_discussion_layer: bool = False
    enable_offturn_self_regulate: bool = False
    enable_offturn_chatter: bool = False
    enable_blinds: bool = False
    small_blind: int = 5
    big_blind: int = 10
    continue_until_survivors: int = 0
    eliminate_on_bankroll_zero: bool = False
    ongoing_table: bool = False
    model_context_window: int = 8192
    log_dir: str = "runs"
    advance_per_table: int = 1
    stakes_multiplier: float = 1.5


class TournamentRunner:
    def __init__(self, cfg: TournamentConfig) -> None:
        self.cfg = cfg
        if cfg.seat_format not in {6, 8}:
            raise ValueError("seat_format must be 6 or 8")
        if cfg.entrants < 2:
            raise ValueError("entrants must be >= 2")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.tournament_id = f"tournament_{stamp}_{uuid.uuid4().hex[:6]}"
        self.event_logger = EventLogger.create(cfg.log_dir, self.tournament_id)

    def run(self) -> dict:
        entrants = self._build_entrants()
        self.event_logger.write(
            "tournament_started",
            {
                "tournament_id": self.tournament_id,
                "entrants": len(entrants),
                "seat_format": self.cfg.seat_format,
                "turns_per_game": self.cfg.turns_per_game,
                "advance_per_table": self.cfg.advance_per_table,
            },
        )
        print(
            f"Starting tournament id={self.tournament_id} "
            f"entrants={len(entrants)} seat_format={self.cfg.seat_format}"
        )

        round_index = 1
        active = list(entrants)
        while len(active) > 1:
            tables = self._chunk(active, self.cfg.seat_format)
            ante = max(1, int(round(self.cfg.ante * (self.cfg.stakes_multiplier ** (round_index - 1)))))
            self.event_logger.write(
                "round_started",
                {
                    "tournament_id": self.tournament_id,
                    "round": round_index,
                    "active_players": list(active),
                    "table_count": len(tables),
                    "ante": ante,
                },
            )
            print(f"\n=== Tournament Round {round_index} ===")
            print(f"tables={len(tables)} ante={ante} active={len(active)}")

            next_round: list[str] = []
            for table_idx, table_players in enumerate(tables, start=1):
                table_id = f"R{round_index}T{table_idx}"
                player_models = {pid: self._pick_model_for_player(pid) for pid in table_players}
                self.event_logger.write(
                    "table_spawned",
                    {
                        "tournament_id": self.tournament_id,
                        "round": round_index,
                        "table_id": table_id,
                        "players": list(table_players),
                        "seat_count": self.cfg.seat_format,
                        "ante": ante,
                    },
                )
                print(f"table={table_id} players={','.join(table_players)}")
                sim = DamageSimulator(
                    SimulatorConfig(
                        base_url=self.cfg.base_url,
                        model=self.cfg.model,
                        fallback_models=self.cfg.fallback_models,
                        player_models=player_models,
                        player_ids=list(table_players),
                        api_key=self.cfg.api_key,
                        players=len(table_players),
                        turns=self.cfg.turns_per_game,
                        seed=self.cfg.seed + round_index * 100 + table_idx,
                        ante=ante,
                        min_raise=self.cfg.min_raise,
                        starting_bankroll=self.cfg.starting_bankroll,
                        card_style=self.cfg.card_style,
                        enable_lives=self.cfg.enable_lives,
                        enable_direct_emoter_attacks=self.cfg.enable_direct_emoter_attacks,
                        enable_discussion_layer=self.cfg.enable_discussion_layer,
                        enable_offturn_self_regulate=self.cfg.enable_offturn_self_regulate,
                        enable_offturn_chatter=self.cfg.enable_offturn_chatter,
                        enable_blinds=self.cfg.enable_blinds,
                        small_blind=self.cfg.small_blind,
                        big_blind=self.cfg.big_blind,
                        continue_until_survivors=self.cfg.continue_until_survivors,
                        eliminate_on_bankroll_zero=self.cfg.eliminate_on_bankroll_zero,
                        ongoing_table=self.cfg.ongoing_table,
                        model_context_window=self.cfg.model_context_window,
                        log_dir=self.cfg.log_dir,
                    )
                )
                game_summary = sim.run()
                ranking_ids = [x["player_id"] for x in game_summary["final_state"]]
                slots = max(1, min(self.cfg.advance_per_table, len(ranking_ids)))
                advanced = ranking_ids[:slots]
                next_round.extend(advanced)
                self.event_logger.write(
                    "table_result",
                    {
                        "tournament_id": self.tournament_id,
                        "round": round_index,
                        "table_id": table_id,
                        "game_id": game_summary["game_id"],
                        "ranking": ranking_ids,
                        "advanced": advanced,
                    },
                )

            if len(next_round) == len(active) and len(next_round) > 1:
                # Prevent deadlock when all players keep advancing by reducing to top half.
                cut = max(1, math.ceil(len(next_round) / 2))
                next_round = next_round[:cut]

            self.event_logger.write(
                "round_ended",
                {
                    "tournament_id": self.tournament_id,
                    "round": round_index,
                    "advanced_players": list(next_round),
                },
            )
            active = next_round
            round_index += 1

        champion = active[0] if active else ""
        self.event_logger.write(
            "tournament_ended",
            {
                "tournament_id": self.tournament_id,
                "champion_player_id": champion,
            },
        )
        print(f"\nTournament champion={champion}")
        print(f"Tournament log: {self.event_logger.events_path}")
        return {
            "tournament_id": self.tournament_id,
            "champion_player_id": champion,
        }

    def _build_entrants(self) -> list[str]:
        return [f"E{i + 1}" for i in range(self.cfg.entrants)]

    def _pick_model_for_player(self, player_id: str) -> str:
        mapping = {k.upper(): v for k, v in (self.cfg.player_models or {}).items()}
        if player_id.upper() in mapping:
            return mapping[player_id.upper()]
        return self.cfg.model

    @staticmethod
    def _chunk(items: list[str], size: int) -> list[list[str]]:
        out: list[list[str]] = []
        for i in range(0, len(items), size):
            out.append(items[i : i + size])
        return out
