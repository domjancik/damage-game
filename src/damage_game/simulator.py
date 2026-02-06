from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from dataclasses import dataclass

from .event_log import EventLogger
from .model_router import ModelRouter, ModelRoutingPolicy
from .models import ActionEnvelope, ActionKind, EmotionState, PlayerState, validate_action
from .provider_openai_compat import OpenAICompatibleClient, OpenAICompatibleConfig
from .token_monitor import TokenMonitor

RANKS = "23456789TJQKA"
SUITS = "CDHS"


@dataclass(slots=True)
class SimulatorConfig:
    base_url: str
    model: str
    api_key: str | None = None
    players: int = 4
    turns: int = 3
    model_context_window: int = 8192
    fallback_models: list[str] | None = None
    log_dir: str = "runs"
    seed: int = 42
    ante: int = 10
    min_raise: int = 10
    starting_bankroll: int = 200


class DamageSimulator:
    def __init__(self, cfg: SimulatorConfig) -> None:
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.client = OpenAICompatibleClient(
            OpenAICompatibleConfig(
                base_url=cfg.base_url,
                model=cfg.model,
                api_key=cfg.api_key,
            )
        )
        self.game_id = datetime.now(timezone.utc).strftime("game_%Y%m%dT%H%M%SZ")
        self.event_logger = EventLogger.create(cfg.log_dir, self.game_id)
        self.token_monitor = TokenMonitor()
        self.model_router = ModelRouter(
            ModelRoutingPolicy(
                primary_model=cfg.model,
                fallback_models=list(cfg.fallback_models or []),
            )
        )
        self.players = [
            PlayerState(player_id=f"P{i + 1}", bankroll=cfg.starting_bankroll)
            for i in range(cfg.players)
        ]
        self.pot = 0
        self.current_high_bet = 0
        self._prime_model_router()

    def run(self) -> None:
        print(
            f"Starting simulation game_id={self.game_id} model={self.cfg.model}, "
            f"players={self.cfg.players}, turns={self.cfg.turns}, seed={self.cfg.seed}"
        )
        print(f"Event log: {self.event_logger.events_path}")
        self.event_logger.write(
            "game_started",
            {
                "players": self.cfg.players,
                "turns": self.cfg.turns,
                "primary_model": self.cfg.model,
                "fallback_models": self.cfg.fallback_models or [],
                "seed": self.cfg.seed,
            },
        )

        for turn in range(1, self.cfg.turns + 1):
            alive = [p for p in self.players if p.lives > 0]
            if len(alive) <= 1:
                break
            print(f"\n=== Hand {turn} ===")
            self._run_hand(turn)
            self._log_turn_summary(turn)

        self.event_logger.write(
            "game_ended",
            {
                "final_state": [self._public_player_state(p) for p in self.players],
                "token_stats": self.token_monitor.stats(),
                "token_stats_by_model": self.token_monitor.stats_by_model(),
            },
        )
        self._print_final_state()

    def _run_hand(self, turn: int) -> None:
        participants = [p for p in self.players if p.lives > 0]
        if len(participants) <= 1:
            return

        self._setup_hand(participants, turn)
        self.event_logger.write("phase_changed", {"turn": turn, "phase": "betting"})
        self._betting_round(participants, turn)
        self.event_logger.write("phase_changed", {"turn": turn, "phase": "showdown"})
        winners, rankings = self._showdown(participants)
        self._apply_hand_outcome(participants, winners, rankings, turn)

    def _setup_hand(self, participants: list[PlayerState], turn: int) -> None:
        deck = [r + s for r in RANKS for s in SUITS]
        self.rng.shuffle(deck)
        self.pot = 0
        self.current_high_bet = 0

        for p in participants:
            p.in_hand = True
            p.hand = [deck.pop(), deck.pop(), deck.pop(), deck.pop(), deck.pop()]
            p.current_bet = 0

            ante_paid = min(self.cfg.ante, max(0, p.bankroll))
            p.bankroll -= ante_paid
            p.current_bet += ante_paid
            self.pot += ante_paid
            self.current_high_bet = max(self.current_high_bet, p.current_bet)

        print(
            f"Hand setup: participants={len(participants)} ante={self.cfg.ante} "
            f"pot={self.pot} high_bet={self.current_high_bet}"
        )
        self.event_logger.write(
            "hand_started",
            {
                "turn": turn,
                "pot": self.pot,
                "ante": self.cfg.ante,
                "players": [self._public_player_state(p) for p in participants],
            },
        )

    def _betting_round(self, participants: list[PlayerState], turn: int) -> None:
        raises_seen = True
        cycle = 0
        while raises_seen and cycle < 2:
            raises_seen = False
            cycle += 1
            for actor in participants:
                if not actor.in_hand or actor.lives <= 0:
                    continue
                action = self._ask_player_for_action(actor, participants, turn)
                was_raise = self._apply_betting_action(actor, action, turn)
                raises_seen = raises_seen or was_raise
                if len([p for p in participants if p.in_hand]) <= 1:
                    return

    def _ask_player_for_action(
        self, actor: PlayerState, participants: list[PlayerState], turn: int
    ) -> ActionEnvelope:
        others = [p for p in participants if p.player_id != actor.player_id and p.in_hand]
        if not others:
            return ActionEnvelope(player_id=actor.player_id, kind=ActionKind.CHECK)

        to_call = max(0, self.current_high_bet - actor.current_bet)
        legal: list[str] = ["fold"]
        if to_call == 0:
            legal.append("check")
        else:
            legal.append("call")
        if actor.bankroll > to_call + self.cfg.min_raise:
            legal.append("raise")

        target = min(others, key=lambda p: p.bankroll)
        public_state = {
            "turn": turn,
            "pot": self.pot,
            "current_high_bet": self.current_high_bet,
            "to_call": to_call,
            "legal_actions": legal,
            "min_raise": self.cfg.min_raise,
            "players": [
                {
                    "player_id": p.player_id,
                    "lives": p.lives,
                    "bankroll": p.bankroll,
                    "current_bet": p.current_bet,
                    "in_hand": p.in_hand,
                }
                for p in participants
            ],
            "self": {
                "player_id": actor.player_id,
                "hand": actor.hand,
                "bankroll": actor.bankroll,
                "to_call": to_call,
                "emotions": self._emotion_dict(actor.emotions),
            },
            "recommended_target": target.player_id,
        }

        system_prompt = (
            "You are an LLM player in a high-stakes poker-like card game. Return only JSON. "
            "Aggressive raises must include an attack_plan describing emotional manipulation."
        )
        user_prompt = (
            "Choose one legal action from legal_actions. "
            "Schema: {kind, payload, attack_plan, reasoning_summary}. "
            "Use kind in [fold, check, call, raise]. "
            "reasoning_summary must be one short sentence (max 20 words) describing intent for observers. "
            "If kind is raise, payload.amount must be an integer > 0 and attack_plan is required with: "
            "kinetic_intent, emotional_intent, manipulation_plan, delivery_channel, target_player_id, "
            "expected_behavior_shift, confidence. "
            f"State: {json.dumps(public_state)}"
        )

        selected_model = self.model_router.pick_action_model(
            actor_tilt=actor.emotions.tilt, actor_exposure=actor.exposure
        )
        max_output_tokens = self.token_monitor.recommended_max_output_tokens(
            self.cfg.model_context_window
        )
        self.event_logger.write(
            "thinking",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "status": "start",
                "model": selected_model,
            },
        )
        try:
            response = self.client.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_output_tokens,
                model=selected_model,
            )
        except Exception as exc:
            self.event_logger.write(
                "action_rejected",
                {
                    "turn": turn,
                    "player_id": actor.player_id,
                    "reason": "provider_failure",
                    "detail": str(exc),
                },
            )
            self.event_logger.write(
                "thinking",
                {"turn": turn, "player_id": actor.player_id, "status": "end", "outcome": "provider_failure"},
            )
            return ActionEnvelope.from_obj({"kind": "call"}, player_id=actor.player_id)

        self.token_monitor.record(actor.player_id, response.model, response.usage)
        self.event_logger.write(
            "provider_call",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "requested_model": selected_model,
                "resolved_model": response.model,
                "latency_ms": response.latency_ms,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "max_output_tokens": max_output_tokens,
            },
        )

        action = ActionEnvelope.from_obj(self._parse_json(response.content), player_id=actor.player_id)
        try:
            validate_action(action)
        except Exception:
            if to_call > 0:
                action = ActionEnvelope.from_obj({"kind": "call"}, player_id=actor.player_id)
            else:
                action = ActionEnvelope.from_obj({"kind": "check"}, player_id=actor.player_id)
        if action.kind.value not in legal:
            action = ActionEnvelope.from_obj({"kind": legal[0]}, player_id=actor.player_id)
        if not action.reasoning_summary.strip():
            action.reasoning_summary = self._fallback_reasoning_summary(action)

        self.event_logger.write(
            "action_submitted",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "action": self._serialize_action(action),
            },
        )
        self.event_logger.write(
            "thinking",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "status": "end",
                "outcome": "action_submitted",
                "summary": action.reasoning_summary[:220],
            },
        )
        return action

    def _apply_betting_action(self, actor: PlayerState, action: ActionEnvelope, turn: int) -> bool:
        to_call = max(0, self.current_high_bet - actor.current_bet)
        was_raise = False

        if action.kind == ActionKind.FOLD:
            actor.in_hand = False
            actor.exposure = min(actor.exposure + 1, 10)
        elif action.kind == ActionKind.CHECK:
            pass
        elif action.kind == ActionKind.CALL:
            commit = min(to_call, actor.bankroll)
            actor.bankroll -= commit
            actor.current_bet += commit
            self.pot += commit
        elif action.kind == ActionKind.RAISE:
            raise_amount = int(action.payload.get("amount", self.cfg.min_raise))
            raise_amount = max(self.cfg.min_raise, raise_amount)
            commit = min(actor.bankroll, to_call + raise_amount)
            actor.bankroll -= commit
            actor.current_bet += commit
            self.pot += commit
            self.current_high_bet = max(self.current_high_bet, actor.current_bet)
            was_raise = True
            target = self._find_player(action.attack_plan.target_player_id) if action.attack_plan else None
            if target is not None:
                self._apply_affective_effects(target, action.attack_plan.emotional_intent.value)
                actor.tempo += 1
        else:
            if to_call > 0:
                commit = min(to_call, actor.bankroll)
                actor.bankroll -= commit
                actor.current_bet += commit
                self.pot += commit

        print(
            f"{actor.player_id} action={action.kind.value} to_call={to_call} "
            f"bet={actor.current_bet} bankroll={actor.bankroll} pot={self.pot}"
        )
        self.event_logger.write(
            "action_resolved",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "kind": action.kind.value,
                "pot": self.pot,
                "current_high_bet": self.current_high_bet,
                "player_state": self._public_player_state(actor),
                "attack_plan": self._serialize_attack_plan(action),
            },
        )
        return was_raise

    def _showdown(self, participants: list[PlayerState]) -> tuple[list[PlayerState], dict[str, dict]]:
        contenders = [p for p in participants if p.in_hand]
        if len(contenders) == 1:
            only = contenders[0]
            rankings = {only.player_id: {"category": "walk", "score": [99]}}
            return [only], rankings

        rankings: dict[str, dict] = {}
        best_score: tuple[int, tuple[int, ...]] | None = None
        winners: list[PlayerState] = []
        for p in contenders:
            category, score, name = evaluate_hand(p.hand)
            rankings[p.player_id] = {
                "category": name,
                "score": [category, *score],
                "hand": list(p.hand),
            }
            combined = (category, score)
            if best_score is None or combined > best_score:
                best_score = combined
                winners = [p]
            elif combined == best_score:
                winners.append(p)
        return winners, rankings

    def _apply_hand_outcome(
        self,
        participants: list[PlayerState],
        winners: list[PlayerState],
        rankings: dict[str, dict],
        turn: int,
    ) -> None:
        winner_ids = {p.player_id for p in winners}
        share = self.pot // max(1, len(winners))
        remainder = self.pot - share * len(winners)

        for idx, w in enumerate(winners):
            payout = share + (1 if idx < remainder else 0)
            w.bankroll += payout

        life_losses = 0
        for p in participants:
            if p.player_id not in winner_ids and p.in_hand:
                life_losses += 1
                p.lives -= 1
                p.exposure = min(10, p.exposure + 1)
                if p.lives <= 0:
                    p.in_hand = False
                self.event_logger.write(
                    "player_eliminated" if p.lives <= 0 else "life_lost",
                    {"turn": turn, "player_id": p.player_id, "remaining_lives": p.lives},
                )

            elif p.player_id not in winner_ids and not p.in_hand:
                # Folding exits life risk for this hand; chip loss is already paid into the pot.
                self.event_logger.write(
                    "fold_saved_life",
                    {"turn": turn, "player_id": p.player_id},
                )
        self.event_logger.write(
            "showdown",
            {
                "turn": turn,
                "pot": self.pot,
                "winners": list(winner_ids),
                "life_losses": life_losses,
                "rankings": rankings,
            },
        )
        self.event_logger.write(
            "hand_ended",
            {
                "turn": turn,
                "players": [self._public_player_state(p) for p in self.players],
            },
        )
        print(
            f"Showdown winners={','.join(sorted(winner_ids))} pot={self.pot} "
            f"losers_life_loss={life_losses}"
        )

    def _log_turn_summary(self, turn: int) -> None:
        stats = self.token_monitor.stats()
        print(
            "Token usage "
            f"calls={int(stats['calls'])} avg_total={stats['avg_total']:.1f} "
            f"p95_total={stats['p95_total']:.1f} required_context_capacity={stats['required_context_capacity']:.0f}"
        )
        warning = self.token_monitor.context_warning(self.cfg.model_context_window)
        if warning:
            print(f"Context warning: {warning}")
        self.event_logger.write(
            "turn_summary",
            {
                "turn": turn,
                "token_stats": stats,
                "token_stats_by_model": self.token_monitor.stats_by_model(),
                "context_warning": warning,
            },
        )

    def _apply_affective_effects(self, target: PlayerState, emotional_intent: str) -> None:
        e = target.emotions
        if emotional_intent == "fear":
            e.fear = min(1.0, e.fear + 0.2)
            e.confidence = max(-1.0, e.confidence - 0.1)
        elif emotional_intent == "anger":
            e.anger = min(1.0, e.anger + 0.2)
            e.tilt = min(1.0, e.tilt + 0.1)
        elif emotional_intent == "shame":
            e.shame = min(1.0, e.shame + 0.2)
            e.confidence = max(-1.0, e.confidence - 0.1)
        elif emotional_intent == "tilt":
            e.tilt = min(1.0, e.tilt + 0.25)
        elif emotional_intent == "overconfidence":
            e.confidence = min(1.0, e.confidence + 0.2)
            e.tilt = min(1.0, e.tilt + 0.1)
        elif emotional_intent == "paranoia":
            e.fear = min(1.0, e.fear + 0.15)
            e.tilt = min(1.0, e.tilt + 0.15)

    def _print_final_state(self) -> None:
        print("\nFinal state")
        for p in self.players:
            em = p.emotions
            print(
                f"{p.player_id}: lives={p.lives} bankroll={p.bankroll} in_hand={p.in_hand} "
                f"tempo={p.tempo} exposure={p.exposure} fear={em.fear:.2f} anger={em.anger:.2f} "
                f"shame={em.shame:.2f} confidence={em.confidence:.2f} tilt={em.tilt:.2f}"
            )

    def _find_player(self, player_id: str) -> PlayerState | None:
        for p in self.players:
            if p.player_id == player_id:
                return p
        return None

    @staticmethod
    def _parse_json(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return {"kind": "fold"}

    def _prime_model_router(self) -> None:
        try:
            available = self.client.list_models()
        except Exception:
            available = []
        self.model_router.set_available_models(available)
        if available:
            print("Available routed models:")
            for model in available:
                print(f"- {model}")

    @staticmethod
    def _serialize_action(action: ActionEnvelope) -> dict:
        out = {
            "player_id": action.player_id,
            "kind": action.kind.value,
            "payload": action.payload,
            "reasoning_summary": action.reasoning_summary,
        }
        out["attack_plan"] = DamageSimulator._serialize_attack_plan(action)
        return out

    @staticmethod
    def _serialize_attack_plan(action: ActionEnvelope) -> dict | None:
        if not action.attack_plan:
            return None
        return {
            "kinetic_intent": action.attack_plan.kinetic_intent.value,
            "emotional_intent": action.attack_plan.emotional_intent.value,
            "manipulation_plan": action.attack_plan.manipulation_plan.value,
            "delivery_channel": action.attack_plan.delivery_channel.value,
            "target_player_id": action.attack_plan.target_player_id,
            "expected_behavior_shift": action.attack_plan.expected_behavior_shift,
            "confidence": action.attack_plan.confidence,
        }

    @staticmethod
    def _emotion_dict(em: EmotionState) -> dict:
        return {
            "fear": em.fear,
            "anger": em.anger,
            "shame": em.shame,
            "confidence": em.confidence,
            "tilt": em.tilt,
        }

    def _public_player_state(self, player: PlayerState) -> dict:
        return {
            "player_id": player.player_id,
            "lives": player.lives,
            "bankroll": player.bankroll,
            "current_bet": player.current_bet,
            "in_hand": player.in_hand,
            "hand": list(player.hand),
            "tempo": player.tempo,
            "exposure": player.exposure,
            "emotions": self._emotion_dict(player.emotions),
        }

    @staticmethod
    def _fallback_reasoning_summary(action: ActionEnvelope) -> str:
        if action.kind == ActionKind.FOLD:
            return "Risk too high for current hand and pot odds."
        if action.kind == ActionKind.CHECK:
            return "No pressure needed; preserve bankroll and observe opponents."
        if action.kind == ActionKind.CALL:
            return "Calling to continue with current equity and pot odds."
        if action.kind == ActionKind.RAISE:
            ap = action.attack_plan
            if ap:
                return (
                    f"Applying pressure via raise to induce {ap.emotional_intent.value} "
                    f"and shift target behavior."
                )
            return "Raising to pressure opponents and grow expected value."
        return "Taking a conservative default line."


def evaluate_hand(cards: list[str]) -> tuple[int, tuple[int, ...], str]:
    ranks = sorted((RANKS.index(c[0]) + 2 for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    rank_counts: dict[int, int] = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1

    groups = sorted(((cnt, rank) for rank, cnt in rank_counts.items()), reverse=True)
    is_flush = len(set(suits)) == 1
    uniq = sorted(set(ranks), reverse=True)
    is_straight = len(uniq) == 5 and uniq[0] - uniq[-1] == 4
    if uniq == [14, 5, 4, 3, 2]:
        is_straight = True
        ranks = [5, 4, 3, 2, 1]

    if is_straight and is_flush:
        return (8, tuple(ranks), "straight_flush")
    if groups[0][0] == 4:
        four = groups[0][1]
        kicker = max(r for r in ranks if r != four)
        return (7, (four, kicker), "four_kind")
    if groups[0][0] == 3 and groups[1][0] == 2:
        return (6, (groups[0][1], groups[1][1]), "full_house")
    if is_flush:
        return (5, tuple(ranks), "flush")
    if is_straight:
        return (4, tuple(ranks), "straight")
    if groups[0][0] == 3:
        three = groups[0][1]
        kickers = tuple(r for r in ranks if r != three)
        return (3, (three, *kickers), "three_kind")
    if groups[0][0] == 2 and groups[1][0] == 2:
        pair_hi = max(groups[0][1], groups[1][1])
        pair_lo = min(groups[0][1], groups[1][1])
        kicker = max(r for r in ranks if r not in {pair_hi, pair_lo})
        return (2, (pair_hi, pair_lo, kicker), "two_pair")
    if groups[0][0] == 2:
        pair = groups[0][1]
        kickers = tuple(r for r in ranks if r != pair)
        return (1, (pair, *kickers), "pair")
    return (0, tuple(ranks), "high_card")
