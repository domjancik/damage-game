from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass

from .event_log import EventLogger
from .model_router import ModelRouter, ModelRoutingPolicy
from .models import ActionEnvelope, ActionKind, EmotionState, PlayerState, validate_action
from .provider_openai_compat import OpenAICompatibleClient, OpenAICompatibleConfig
from .token_monitor import TokenMonitor


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


class DamageSimulator:
    def __init__(self, cfg: SimulatorConfig) -> None:
        self.cfg = cfg
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
        self.players = [PlayerState(player_id=f"P{i + 1}") for i in range(cfg.players)]
        self._prime_model_router()

    def run(self) -> None:
        print(
            f"Starting simulation game_id={self.game_id} model={self.cfg.model}, "
            f"players={self.cfg.players}, turns={self.cfg.turns}"
        )
        print(f"Event log: {self.event_logger.events_path}")
        self.event_logger.write(
            "game_started",
            {
                "players": self.cfg.players,
                "turns": self.cfg.turns,
                "primary_model": self.cfg.model,
                "fallback_models": self.cfg.fallback_models or [],
            },
        )
        for turn in range(1, self.cfg.turns + 1):
            print(f"\n=== Turn {turn} ===")
            self.event_logger.write("phase_changed", {"turn": turn, "phase": "action"})
            for actor in self.players:
                action = self._ask_player_for_action(actor, turn)
                self._apply_action(actor, action)

            self._check_elimination()
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

        self.event_logger.write(
            "game_ended",
            {
                "final_state": [self._public_player_state(p) for p in self.players],
                "token_stats": self.token_monitor.stats(),
                "token_stats_by_model": self.token_monitor.stats_by_model(),
            },
        )
        self._print_final_state()

    def _ask_player_for_action(self, actor: PlayerState, turn: int) -> ActionEnvelope:
        others = [p for p in self.players if p.player_id != actor.player_id and p.lives > 0]
        if not others:
            return ActionEnvelope(player_id=actor.player_id, kind=ActionKind.PASS)

        target = min(others, key=lambda p: p.resolve)
        public_state = {
            "turn": turn,
            "players": [
                {
                    "player_id": p.player_id,
                    "lives": p.lives,
                    "resolve": p.resolve,
                    "tempo": p.tempo,
                    "exposure": p.exposure,
                }
                for p in self.players
            ],
            "self": {
                "player_id": actor.player_id,
                "emotions": {
                    "fear": actor.emotions.fear,
                    "anger": actor.emotions.anger,
                    "shame": actor.emotions.shame,
                    "confidence": actor.emotions.confidence,
                    "tilt": actor.emotions.tilt,
                },
            },
            "recommended_target": target.player_id,
        }

        system_prompt = (
            "You are an LLM player in a high-stakes card game. Return only JSON. "
            "Every non-trivial attack must include a complete attack_plan with both kinetic and emotional intent."
        )
        user_prompt = (
            "Choose one legal action. Prefer play_card or pass. "
            "Schema: {kind, payload, attack_plan, reasoning_summary}. "
            "If kind is play_card/activate/reaction and non_trivial=true, attack_plan is required with: "
            "kinetic_intent, emotional_intent, manipulation_plan, delivery_channel, target_player_id, "
            "expected_behavior_shift, confidence. "
            f"State: {json.dumps(public_state)}"
        )

        selected_model = self.model_router.pick_action_model(actor_tilt=actor.emotions.tilt, actor_exposure=actor.exposure)
        max_output_tokens = self.token_monitor.recommended_max_output_tokens(self.cfg.model_context_window)
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
            fallback = {
                "kind": "pass",
                "payload": {"non_trivial": False},
                "reasoning_summary": "Provider failure fallback",
            }
            return ActionEnvelope.from_obj(fallback, player_id=actor.player_id)

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

        parsed = self._parse_json(response.content)
        action = ActionEnvelope.from_obj(parsed, player_id=actor.player_id)

        try:
            validate_action(action)
        except Exception as exc:
            self.event_logger.write(
                "action_rejected",
                {
                    "turn": turn,
                    "player_id": actor.player_id,
                    "reason": "schema_validation_failed",
                    "detail": str(exc),
                    "raw_response": response.content,
                },
            )
            fallback = {
                "kind": "pass",
                "payload": {"non_trivial": False},
                "reasoning_summary": "Fallback pass after validation failure",
            }
            action = ActionEnvelope.from_obj(fallback, player_id=actor.player_id)

        self.event_logger.write(
            "action_submitted",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "action": self._serialize_action(action),
            },
        )
        return action

    def _apply_action(self, actor: PlayerState, action: ActionEnvelope) -> None:
        if action.kind == ActionKind.PASS:
            actor.exposure = max(0, actor.exposure - 1)
            print(f"{actor.player_id} passes")
            self.event_logger.write(
                "action_resolved",
                {
                    "player_id": actor.player_id,
                    "kind": action.kind.value,
                    "tactical_effect": {"exposure_delta": -1},
                    "affective_effect": {},
                },
            )
            return

        if not action.attack_plan:
            actor.exposure += 1
            print(f"{actor.player_id} attempted non-attack action without attack plan; exposure+1")
            self.event_logger.write(
                "action_resolved",
                {
                    "player_id": actor.player_id,
                    "kind": action.kind.value,
                    "tactical_effect": {"exposure_delta": +1},
                    "affective_effect": {},
                    "notes": ["missing_attack_plan"],
                },
            )
            return

        target = self._find_player(action.attack_plan.target_player_id)
        if target is None or target.lives <= 0:
            actor.exposure += 1
            print(f"{actor.player_id} targeted invalid player; exposure+1")
            self.event_logger.write(
                "action_resolved",
                {
                    "player_id": actor.player_id,
                    "kind": action.kind.value,
                    "tactical_effect": {"exposure_delta": +1},
                    "affective_effect": {},
                    "notes": ["invalid_target"],
                },
            )
            return

        tactical_damage = 1 + (1 if action.attack_plan.kinetic_intent.value == "tempo_swing" else 0)
        target.resolve -= tactical_damage
        actor.tempo += 1

        self._apply_affective_effects(target, action.attack_plan.emotional_intent.value)

        print(
            f"{actor.player_id} -> {target.player_id} kind={action.kind.value} "
            f"kinetic={action.attack_plan.kinetic_intent.value} "
            f"emotional={action.attack_plan.emotional_intent.value} "
            f"resolve_delta=-{tactical_damage}"
        )
        self.event_logger.write(
            "action_resolved",
            {
                "actor_player_id": actor.player_id,
                "target_player_id": target.player_id,
                "kind": action.kind.value,
                "attack_plan": {
                    "kinetic_intent": action.attack_plan.kinetic_intent.value,
                    "emotional_intent": action.attack_plan.emotional_intent.value,
                    "manipulation_plan": action.attack_plan.manipulation_plan.value,
                    "delivery_channel": action.attack_plan.delivery_channel.value,
                    "expected_behavior_shift": action.attack_plan.expected_behavior_shift,
                    "confidence": action.attack_plan.confidence,
                },
                "tactical_effect": {
                    "resolve_delta": {target.player_id: -tactical_damage},
                    "tempo_delta": {actor.player_id: +1},
                },
                "affective_effect": {
                    "target_emotions": self._emotion_dict(target.emotions),
                },
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

    def _check_elimination(self) -> None:
        for p in self.players:
            if p.lives <= 0:
                continue
            if p.resolve <= 0:
                p.lives -= 1
                p.resolve = 8
                p.tempo = max(0, p.tempo - 1)
                p.exposure = max(0, p.exposure - 1)
                print(f"{p.player_id} lost a Life. Remaining lives={p.lives}")
                self.event_logger.write(
                    "player_eliminated" if p.lives <= 0 else "life_lost",
                    {"player_id": p.player_id, "remaining_lives": p.lives},
                )

    def _print_final_state(self) -> None:
        print("\nFinal state")
        for p in self.players:
            em = p.emotions
            print(
                f"{p.player_id}: lives={p.lives} resolve={p.resolve} tempo={p.tempo} exposure={p.exposure} "
                f"fear={em.fear:.2f} anger={em.anger:.2f} shame={em.shame:.2f} confidence={em.confidence:.2f} tilt={em.tilt:.2f}"
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
                return json.loads(text[start : end + 1])
            return {"kind": "pass", "payload": {"non_trivial": False}}

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
        if action.attack_plan:
            out["attack_plan"] = {
                "kinetic_intent": action.attack_plan.kinetic_intent.value,
                "emotional_intent": action.attack_plan.emotional_intent.value,
                "manipulation_plan": action.attack_plan.manipulation_plan.value,
                "delivery_channel": action.attack_plan.delivery_channel.value,
                "target_player_id": action.attack_plan.target_player_id,
                "expected_behavior_shift": action.attack_plan.expected_behavior_shift,
                "confidence": action.attack_plan.confidence,
            }
        return out

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
            "resolve": player.resolve,
            "tempo": player.tempo,
            "exposure": player.exposure,
            "emotions": self._emotion_dict(player.emotions),
        }
