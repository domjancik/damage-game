from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from itertools import combinations

from .event_log import EventLogger
from .model_router import ModelRouter, ModelRoutingPolicy
from .models import ActionEnvelope, ActionKind, EmotionState, PlayerState, validate_action
from .provider_openai_compat import OpenAICompatibleClient, OpenAICompatibleConfig
from .token_monitor import TokenMonitor

RANKS = "23456789TJQKA"
SUITS = "CDHS"
AVATAR_IDS = [
    "pilot_ace",
    "stoic_oracle",
    "bluff_knight",
    "cold_mirror",
    "trickster",
    "iron_reader",
    "quiet_storm",
    "vector_hawk",
]


@dataclass(slots=True)
class SimulatorConfig:
    base_url: str
    model: str
    api_key: str | None = None
    players: int = 4
    turns: int = 3
    model_context_window: int = 8192
    fallback_models: list[str] | None = None
    player_models: dict[str, str] | None = None
    player_ids: list[str] | None = None
    log_dir: str = "runs"
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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.game_id = f"game_{stamp}_{uuid.uuid4().hex[:6]}"
        self.event_logger = EventLogger.create(cfg.log_dir, self.game_id)
        self.token_monitor = TokenMonitor()
        self.model_router = ModelRouter(
            ModelRoutingPolicy(
                primary_model=cfg.model,
                fallback_models=list(cfg.fallback_models or []),
            )
        )
        self.player_models = {k.upper(): v for k, v in (cfg.player_models or {}).items()}
        self.card_style = (cfg.card_style or "draw5").strip().lower()
        if self.card_style not in {"draw5", "holdem"}:
            self.card_style = "draw5"
        self.available_models: set[str] = set()
        configured_ids = [x.strip() for x in (cfg.player_ids or []) if x.strip()]
        if configured_ids:
            player_ids = configured_ids
        else:
            player_ids = [f"P{i + 1}" for i in range(cfg.players)]
        self.players = [
            PlayerState(
                player_id=player_id,
                bankroll=cfg.starting_bankroll,
                will=self.rng.randint(50, 75),
                skill_affect=self.rng.randint(45, 80),
            )
            for player_id in player_ids
        ]
        self.pot = 0
        self.current_high_bet = 0
        self.community_cards: list[str] = []
        self._community_deck_cards: list[str] = []
        self._prime_model_router()

    def run(self) -> dict:
        print(
            f"Starting simulation game_id={self.game_id} model={self.cfg.model}, "
            f"players={len(self.players)}, turns={self.cfg.turns}, seed={self.cfg.seed}, card_style={self.card_style}"
        )
        if self.player_models:
            print("Per-player model assignment:")
            for pid in sorted(self.player_models):
                print(f"- {pid}: {self.player_models[pid]}")
        print(f"Event log: {self.event_logger.events_path}")
        self.event_logger.write(
            "game_started",
            {
                "players": len(self.players),
                "player_ids": [p.player_id for p in self.players],
                "turns": self.cfg.turns,
                "primary_model": self.cfg.model,
                "fallback_models": self.cfg.fallback_models or [],
                "seed": self.cfg.seed,
                "card_style": self.card_style,
                "enable_lives": self.cfg.enable_lives,
                "enable_direct_emoter_attacks": self.cfg.enable_direct_emoter_attacks,
                "enable_discussion_layer": self.cfg.enable_discussion_layer,
                "enable_offturn_self_regulate": self.cfg.enable_offturn_self_regulate,
                "enable_offturn_chatter": self.cfg.enable_offturn_chatter,
            },
        )
        self._select_player_avatars()

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
        ranked = sorted(
            (self._public_player_state(p) for p in self.players),
            key=lambda x: (int(x["lives"]), int(x["bankroll"]), int(x["tempo"])),
            reverse=True,
        )
        top_key = None
        if ranked:
            top = ranked[0]
            top_key = (int(top["lives"]), int(top["bankroll"]), int(top["tempo"]))
        winners = []
        for item in ranked:
            k = (int(item["lives"]), int(item["bankroll"]), int(item["tempo"]))
            if top_key is not None and k == top_key:
                winners.append(item["player_id"])
        return {
            "game_id": self.game_id,
            "final_state": ranked,
            "winners": winners,
        }

    def _run_hand(self, turn: int) -> None:
        participants = [p for p in self.players if p.lives > 0]
        if len(participants) <= 1:
            return

        self._setup_hand(participants, turn)
        self.event_logger.write("phase_changed", {"turn": turn, "phase": "affect"})
        self._affect_phase(participants, turn)
        if self.cfg.enable_discussion_layer:
            self.event_logger.write("phase_changed", {"turn": turn, "phase": "discussion"})
            self._discussion_phase(participants, turn)
        self.event_logger.write("phase_changed", {"turn": turn, "phase": "betting"})
        self._betting_round(participants, turn)
        self.event_logger.write("phase_changed", {"turn": turn, "phase": "showdown"})
        winners, rankings, powers = self._showdown(participants)
        self._apply_hand_outcome(participants, winners, rankings, powers, turn)

    def _setup_hand(self, participants: list[PlayerState], turn: int) -> None:
        deck = [r + s for r in RANKS for s in SUITS]
        self.rng.shuffle(deck)
        self.pot = 0
        self.current_high_bet = 0
        self.community_cards = []
        self._community_deck_cards = []
        if self.card_style == "holdem":
            self._community_deck_cards = [deck.pop(), deck.pop(), deck.pop(), deck.pop(), deck.pop()]

        for p in participants:
            p.in_hand = True
            if self.card_style == "holdem":
                p.hand = [deck.pop(), deck.pop()]
            else:
                p.hand = [deck.pop(), deck.pop(), deck.pop(), deck.pop(), deck.pop()]
            p.current_bet = 0
            p.hand_contribution = 0
            p.resistance_bonus = 0.0
            p.hand_emotion_shift = {"fear": 0.0, "anger": 0.0, "shame": 0.0, "confidence": 0.0, "tilt": 0.0}
            p.focus = min(100.0, p.focus + 14.0)
            p.stress = max(0.0, p.stress - 10.0)

            ante_paid = min(self.cfg.ante, max(0, p.bankroll))
            p.bankroll -= ante_paid
            p.hand_contribution += ante_paid
            self.pot += ante_paid
        self.current_high_bet = 0

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
                "card_style": self.card_style,
                "community_cards": list(self.community_cards),
                "players": [self._public_player_state(p) for p in participants],
            },
        )

    def _affect_phase(self, participants: list[PlayerState], turn: int) -> None:
        intents: dict[str, dict] = {}
        for actor in participants:
            if not actor.in_hand or actor.lives <= 0:
                continue
            intent = self._ask_player_for_affect(actor, participants, turn)
            intents[actor.player_id] = intent

        attacks: dict[str, dict] = {}
        pending_assists: list[dict] = []
        assists_by_lead: dict[str, list[dict]] = {}
        for pid, intent in intents.items():
            mode = intent.get("mode", "none")
            actor = self._find_player(pid)
            if actor is None:
                continue
            spend = self._commit_focus(actor, int(intent.get("focus_spend", 0)))
            if mode == "self_regulate":
                # Convert focus into bounded emotional recovery for the actor.
                recover = min(25.0, spend * 1.4 + actor.skill_affect * 0.15)
                actor.stress = clampf(actor.stress - recover, 0.0, 100.0)

                tilt_delta = self._cap_hand_emotion_delta(actor, "tilt", -min(0.20, 0.03 + spend / 180.0), 0.6)
                fear_delta = self._cap_hand_emotion_delta(actor, "fear", -min(0.12, 0.02 + spend / 220.0), 0.6)
                conf_delta = self._cap_hand_emotion_delta(actor, "confidence", min(0.10, 0.02 + spend / 260.0), 0.6)
                self._apply_single_emotion_delta(actor, "tilt", tilt_delta)
                self._apply_single_emotion_delta(actor, "fear", fear_delta)
                self._apply_single_emotion_delta(actor, "confidence", conf_delta)
                self.event_logger.write(
                    "affect_resolved",
                    {
                        "turn": turn,
                        "mode": "self_regulate",
                        "player_id": actor.player_id,
                        "focus_spent": spend,
                        "stress_recovered": round(recover, 3),
                        "deltas": {
                            "tilt": round(tilt_delta, 4),
                            "fear": round(fear_delta, 4),
                            "confidence": round(conf_delta, 4),
                        },
                        "target_emotions": self._emotion_dict(actor.emotions),
                    },
                )
                continue
            if mode == "guard":
                guard = min(30.0, actor.skill_affect * 0.35 + spend * 0.8)
                actor.resistance_bonus += guard
                self.event_logger.write(
                    "affect_resolved",
                    {
                        "turn": turn,
                        "mode": "guard",
                        "player_id": actor.player_id,
                        "focus_spent": spend,
                        "resistance_bonus": actor.resistance_bonus,
                    },
                )
                continue
            if mode == "attack":
                target = str(intent.get("target_player_id", ""))
                if not target or target == actor.player_id:
                    continue
                attacks[actor.player_id] = {
                    "lead_id": actor.player_id,
                    "target_player_id": target,
                    "emotion": str(intent.get("emotion", "fear")),
                    "focus_spend": spend,
                }
                continue
            if mode == "assist":
                lead = str(intent.get("lead_player_id", ""))
                target = str(intent.get("target_player_id", ""))
                if not target:
                    continue
                if lead == actor.player_id:
                    lead = ""
                pending_assists.append(
                    {
                        "assistant_id": actor.player_id,
                        "lead_player_id": lead,
                        "target_player_id": target,
                        "emotion": normalize_emotion(str(intent.get("emotion", "fear"))),
                        "focus_spend": spend,
                    }
                )

        for assist in pending_assists:
            lead = assist.get("lead_player_id", "")
            target = assist["target_player_id"]
            emotion = assist["emotion"]
            assigned_lead = ""
            if lead in attacks:
                atk = attacks[lead]
                if atk["target_player_id"] == target and normalize_emotion(atk["emotion"]) == emotion:
                    assigned_lead = lead
            if not assigned_lead:
                for candidate_lead, atk in attacks.items():
                    if atk["target_player_id"] == target and normalize_emotion(atk["emotion"]) == emotion:
                        assigned_lead = candidate_lead
                        break
            if assigned_lead:
                assists_by_lead.setdefault(assigned_lead, []).append(assist)
            else:
                assistant = self._find_player(assist["assistant_id"])
                target_player = self._find_player(target)
                if assistant is None or target_player is None:
                    self.event_logger.write(
                        "affect_unpaired_assist",
                        {
                            "turn": turn,
                            "assistant_id": assist["assistant_id"],
                            "target_player_id": target,
                            "emotion": emotion,
                            "outcome": "invalid_target_or_assistant",
                        },
                    )
                    continue

                spend = int(assist["focus_spend"])
                direct_power = self._affect_power(assistant, spend)
                # Direct assist should produce visible bounded uplift when focus is committed.
                raw = 0.02 + (direct_power / 700.0) + (spend / 240.0) - (target_player.stress / 800.0)
                delta = clampf(raw, 0.01, 0.18)
                capped = self._cap_hand_emotion_delta(target_player, emotion, delta, 0.6)
                self._apply_single_emotion_delta(target_player, emotion, capped)
                target_player.stress = clampf(target_player.stress + abs(capped) * 10.0, 0.0, 100.0)

                self.event_logger.write(
                    "affect_resolved",
                    {
                        "turn": turn,
                        "mode": "assist_direct",
                        "assistant_id": assistant.player_id,
                        "target_player_id": target_player.player_id,
                        "emotion": emotion,
                        "focus_spent": spend,
                        "raw_delta": round(delta, 4),
                        "applied_delta": round(capped, 4),
                        "target_emotions": self._emotion_dict(target_player.emotions),
                    },
                )

        for lead_id, attack in attacks.items():
            lead = self._find_player(lead_id)
            target = self._find_player(attack["target_player_id"])
            if lead is None or target is None or not target.in_hand:
                continue
            attack_emotion = normalize_emotion(attack["emotion"])
            team = [attack]
            for assist in assists_by_lead.get(lead_id, []):
                if assist["target_player_id"] == target.player_id and normalize_emotion(assist["emotion"]) == attack_emotion:
                    team.append(assist)

            lead_power = self._affect_power(lead, int(attack["focus_spend"]))
            assist_power = 0.0
            for assist in team[1:]:
                assistant = self._find_player(assist["assistant_id"])
                if assistant is not None:
                    assist_power += self._affect_power(assistant, int(assist["focus_spend"]))
            team_power = lead_power + 0.6 * assist_power
            team_power = min(team_power, 2.0 * max(1.0, lead_power))

            stake_base = max(1.0, float(self.cfg.ante * max(1, len(participants))))
            stake_mult = clampf(1.0 + (self.pot / stake_base) * 0.2, 1.0, 1.8)
            attack_score = team_power * stake_mult + self.rng.uniform(-5.0, 5.0)
            defense = target.will + target.resistance_bonus + 0.3 * target.skill_affect + self.rng.uniform(-5.0, 5.0)
            raw = attack_score - defense
            delta = clampf(raw / 120.0, -0.25, 0.25)

            capped = self._cap_hand_emotion_delta(target, attack_emotion, delta, 0.6)
            self._apply_single_emotion_delta(target, attack_emotion, capped)
            target.stress = clampf(target.stress + abs(capped) * 18.0, 0.0, 100.0)

            self.event_logger.write(
                "affect_resolved",
                {
                    "turn": turn,
                    "mode": "attack_team",
                    "lead_player_id": lead_id,
                    "assistants": [x["assistant_id"] for x in team[1:]],
                    "target_player_id": target.player_id,
                    "emotion": attack_emotion,
                    "team_power": round(team_power, 3),
                    "attack_score": round(attack_score, 3),
                    "defense_score": round(defense, 3),
                    "raw_delta": round(delta, 4),
                    "applied_delta": round(capped, 4),
                    "stake_multiplier": round(stake_mult, 3),
                    "target_emotions": self._emotion_dict(target.emotions),
                },
            )

    def _ask_player_for_affect(self, actor: PlayerState, participants: list[PlayerState], turn: int) -> dict:
        active_ids = [p.player_id for p in participants if p.in_hand and p.player_id != actor.player_id]
        if not active_ids:
            return {"mode": "none", "focus_spend": 0}
        focus_budget = int(min(actor.focus, 20.0 + actor.skill_affect / 5.0))
        state = {
            "turn": turn,
            "pot": self.pot,
            "self": {
                "player_id": actor.player_id,
                "will": actor.will,
                "skill_affect": actor.skill_affect,
                "focus": actor.focus,
                "stress": actor.stress,
                "focus_budget": focus_budget,
                "emotions": self._emotion_dict(actor.emotions),
            },
            "players": [
                {
                    "player_id": p.player_id,
                    "in_hand": p.in_hand,
                    "will": p.will,
                    "skill_affect": p.skill_affect,
                    "stress": p.stress,
                }
                for p in participants
            ],
            "valid_emotions": ["fear", "anger", "shame", "confidence", "tilt"],
            "valid_modes": ["attack", "assist", "guard", "self_regulate", "none"],
            "active_ids": active_ids,
        }
        system_prompt = (
            "You are deciding pre-betting affect tactics in a high-stakes game. Return only JSON."
        )
        user_prompt = (
            "Choose one mode: attack/assist/guard/self_regulate/none. "
            "Schema: {mode, target_player_id, lead_player_id, emotion, focus_spend, summary}. "
            "For attack provide target_player_id and emotion. "
            "For assist provide lead_player_id, target_player_id and emotion. "
            "For self_regulate provide focus_spend; target fields can be empty. "
            "focus_spend must be integer between 0 and focus_budget. "
            f"State: {json.dumps(state)}"
        )
        model = self._select_model_for_player(actor)
        max_output_tokens = min(300, self.token_monitor.recommended_max_output_tokens(self.cfg.model_context_window))
        self.event_logger.write(
            "thinking",
            {"turn": turn, "player_id": actor.player_id, "status": "start", "model": model, "stage": "affect"},
        )
        try:
            response = self.client.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_output_tokens,
                model=model,
            )
            self.token_monitor.record(actor.player_id, response.model, response.usage)
        except Exception:
            self.event_logger.write(
                "thinking",
                {"turn": turn, "player_id": actor.player_id, "status": "end", "stage": "affect", "outcome": "provider_failure"},
            )
            return {"mode": "none", "focus_spend": 0}

        parsed = self._parse_json(response.content)
        mode = str(parsed.get("mode", "none")).strip().lower()
        if mode not in {"attack", "assist", "guard", "self_regulate", "none"}:
            mode = "none"
        spend = int(parsed.get("focus_spend", 0))
        spend = max(0, min(spend, focus_budget))
        out = {
            "mode": mode,
            "focus_spend": spend,
            "target_player_id": str(parsed.get("target_player_id", "")),
            "lead_player_id": str(parsed.get("lead_player_id", "")),
            "emotion": normalize_emotion(str(parsed.get("emotion", "fear"))),
            "summary": str(parsed.get("summary", ""))[:160],
        }
        if out["mode"] in {"attack", "assist"}:
            if out["target_player_id"] == actor.player_id or out["target_player_id"] not in active_ids:
                out["target_player_id"] = active_ids[0]
        if out["mode"] == "assist" and out["lead_player_id"] == actor.player_id:
            out["lead_player_id"] = ""
        self.event_logger.write(
            "thinking",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "status": "end",
                "stage": "affect",
                "outcome": "intent_selected",
                "summary": out["summary"],
            },
        )
        self.event_logger.write(
            "affect_intent",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "intent": out,
            },
        )
        return out

    def _discussion_phase(self, participants: list[PlayerState], turn: int) -> None:
        for actor in participants:
            if not actor.in_hand or actor.lives <= 0:
                continue
            chat = self._ask_player_for_chatter(actor, participants, turn)
            message = str(chat.get("message", "")).strip()
            if not message:
                continue
            target_id = str(chat.get("target_player_id", "")).strip()
            target = self._find_player(target_id)
            if target is None or target.player_id == actor.player_id or not target.in_hand:
                choices = [p for p in participants if p.in_hand and p.player_id != actor.player_id]
                if not choices:
                    continue
                target = choices[0]
                target_id = target.player_id
            intended = normalize_emotion(str(chat.get("intended_emotion", "fear")))
            tone = str(chat.get("tone", "neutral")).strip().lower()[:24]
            self.event_logger.write(
                "chatter_posted",
                {
                    "turn": turn,
                    "player_id": actor.player_id,
                    "target_player_id": target_id,
                    "tone": tone or "neutral",
                    "intended_emotion": intended,
                    "message": message[:180],
                },
            )

            eval_out = self._evaluate_chatter_effect(actor, target, message, intended, turn)
            effect_emotion = normalize_emotion(str(eval_out.get("impact_emotion", intended)))
            raw_delta = float(eval_out.get("delta", 0.0))
            raw_delta = clampf(raw_delta, -0.18, 0.18)
            applied = self._cap_hand_emotion_delta(target, effect_emotion, raw_delta, 0.6)
            self._apply_single_emotion_delta(target, effect_emotion, applied)
            target.stress = clampf(target.stress + abs(applied) * 8.0, 0.0, 100.0)
            self.event_logger.write(
                "chatter_evaluated",
                {
                    "turn": turn,
                    "speaker_id": actor.player_id,
                    "target_player_id": target.player_id,
                    "impact_emotion": effect_emotion,
                    "raw_delta": round(raw_delta, 4),
                    "applied_delta": round(applied, 4),
                    "summary": str(eval_out.get("summary", ""))[:180],
                    "target_emotions": self._emotion_dict(target.emotions),
                },
            )

    def _ask_player_for_chatter(self, actor: PlayerState, participants: list[PlayerState], turn: int) -> dict:
        others = [p for p in participants if p.in_hand and p.player_id != actor.player_id]
        if not others:
            return {"message": ""}
        prompt_state = {
            "turn": turn,
            "pot": self.pot,
            "self": {
                "player_id": actor.player_id,
                "emotions": self._emotion_dict(actor.emotions),
                "will": actor.will,
                "skill_affect": actor.skill_affect,
            },
            "targets": [
                {
                    "player_id": p.player_id,
                    "bankroll": p.bankroll,
                    "current_bet": p.current_bet,
                    "stress": p.stress,
                }
                for p in others
            ],
            "valid_emotions": ["fear", "anger", "shame", "confidence", "tilt"],
        }
        model = self._select_model_for_player(actor)
        self.event_logger.write(
            "thinking",
            {"turn": turn, "player_id": actor.player_id, "status": "start", "model": model, "stage": "chatter"},
        )
        try:
            response = self.client.chat_json(
                system_prompt="Produce a short in-game chatter line for psychological pressure. Return JSON only.",
                user_prompt=(
                    "Schema: {target_player_id, intended_emotion, tone, message}. "
                    "message max 18 words. "
                    f"State: {json.dumps(prompt_state)}"
                ),
                max_tokens=160,
                model=model,
            )
            self.token_monitor.record(actor.player_id, response.model, response.usage)
        except Exception:
            self.event_logger.write(
                "thinking",
                {"turn": turn, "player_id": actor.player_id, "status": "end", "stage": "chatter", "outcome": "provider_failure"},
            )
            return {"message": ""}
        parsed = self._parse_json(response.content)
        out = {
            "target_player_id": str(parsed.get("target_player_id", others[0].player_id)),
            "intended_emotion": normalize_emotion(str(parsed.get("intended_emotion", "fear"))),
            "tone": str(parsed.get("tone", "neutral")),
            "message": str(parsed.get("message", "")).strip()[:180],
        }
        self.event_logger.write(
            "thinking",
            {
                "turn": turn,
                "player_id": actor.player_id,
                "status": "end",
                "stage": "chatter",
                "outcome": "chatter_selected",
                "summary": out["message"][:120],
            },
        )
        return out

    def _evaluate_chatter_effect(
        self, speaker: PlayerState, target: PlayerState, message: str, intended_emotion: str, turn: int
    ) -> dict:
        model = self._select_model_for_player(target)
        state = {
            "turn": turn,
            "speaker_id": speaker.player_id,
            "target_id": target.player_id,
            "message": message[:180],
            "intended_emotion": intended_emotion,
            "target_emotions": self._emotion_dict(target.emotions),
            "target_stress": target.stress,
        }
        self.event_logger.write(
            "thinking",
            {"turn": turn, "player_id": target.player_id, "status": "start", "model": model, "stage": "chatter_eval"},
        )
        try:
            response = self.client.chat_json(
                system_prompt="Evaluate emotional impact of one line of table chatter. Return JSON only.",
                user_prompt=(
                    "Schema: {impact_emotion, delta, summary}. "
                    "delta must be float in [-0.18,0.18]. Positive increases the emotion. "
                    f"State: {json.dumps(state)}"
                ),
                max_tokens=140,
                model=model,
            )
            self.token_monitor.record(target.player_id, response.model, response.usage)
            parsed = self._parse_json(response.content)
        except Exception:
            parsed = {
                "impact_emotion": intended_emotion,
                "delta": clampf(
                    0.03 + (speaker.skill_affect - target.will) / 380.0 - target.stress / 1200.0,
                    -0.08,
                    0.12,
                ),
                "summary": "fallback_eval",
            }
        self.event_logger.write(
            "thinking",
            {
                "turn": turn,
                "player_id": target.player_id,
                "status": "end",
                "stage": "chatter_eval",
                "outcome": "evaluated",
                "summary": str(parsed.get("summary", ""))[:120],
            },
        )
        return parsed

    def _commit_focus(self, actor: PlayerState, requested: int) -> int:
        budget = int(min(actor.focus, 20.0 + actor.skill_affect / 5.0))
        spend = max(0, min(requested, budget))
        actor.focus = max(0.0, actor.focus - float(spend))
        actor.stress = clampf(actor.stress + spend * 0.15, 0.0, 100.0)
        return spend

    @staticmethod
    def _affect_power(actor: PlayerState, spend: int) -> float:
        power = 0.45 * actor.skill_affect + 0.35 * actor.will + 0.20 * spend - 0.25 * actor.stress
        return max(0.0, power)

    @staticmethod
    def _cap_hand_emotion_delta(target: PlayerState, emotion: str, delta: float, cap: float) -> float:
        used = float(target.hand_emotion_shift.get(emotion, 0.0))
        remaining_pos = cap - used
        remaining_neg = -cap - used
        capped = clampf(delta, remaining_neg, remaining_pos)
        target.hand_emotion_shift[emotion] = used + capped
        return capped

    @staticmethod
    def _apply_single_emotion_delta(target: PlayerState, emotion: str, delta: float) -> None:
        if emotion == "fear":
            target.emotions.fear = clampf(target.emotions.fear + delta, -1.0, 1.0)
        elif emotion == "anger":
            target.emotions.anger = clampf(target.emotions.anger + delta, -1.0, 1.0)
        elif emotion == "shame":
            target.emotions.shame = clampf(target.emotions.shame + delta, -1.0, 1.0)
        elif emotion == "confidence":
            target.emotions.confidence = clampf(target.emotions.confidence + delta, -1.0, 1.0)
        elif emotion == "tilt":
            target.emotions.tilt = clampf(target.emotions.tilt + delta, -1.0, 1.0)

    def _betting_round(self, participants: list[PlayerState], turn: int) -> None:
        if self.card_style == "holdem":
            self._betting_round_holdem(participants, turn)
            return
        self._betting_cycle(participants, turn)

    def _betting_round_holdem(self, participants: list[PlayerState], turn: int) -> None:
        self._start_street(participants)
        self._betting_cycle(participants, turn)
        if len([p for p in participants if p.in_hand]) <= 1:
            return
        self._reveal_community(turn=turn, street="flop", count=3)

        self._start_street(participants)
        self._betting_cycle(participants, turn)
        if len([p for p in participants if p.in_hand]) <= 1:
            return
        self._reveal_community(turn=turn, street="turn", count=4)

        self._start_street(participants)
        self._betting_cycle(participants, turn)
        if len([p for p in participants if p.in_hand]) <= 1:
            return
        self._reveal_community(turn=turn, street="river", count=5)

        self._start_street(participants)
        self._betting_cycle(participants, turn)

    def _start_street(self, participants: list[PlayerState]) -> None:
        self.current_high_bet = 0
        for p in participants:
            if p.in_hand and p.lives > 0:
                p.current_bet = 0

    def _reveal_community(self, turn: int, street: str, count: int) -> None:
        target = max(0, min(count, len(self._community_deck_cards)))
        if target <= len(self.community_cards):
            return
        before = len(self.community_cards)
        self.community_cards = list(self._community_deck_cards[:target])
        self.event_logger.write(
            "community_revealed",
            {
                "turn": turn,
                "street": street,
                "community_cards": list(self.community_cards),
                "revealed_cards": list(self.community_cards[before:target]),
            },
        )

    def _betting_cycle(self, participants: list[PlayerState], turn: int) -> None:
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
                self._offturn_responses(trigger_actor=actor, participants=participants, turn=turn)
                if len([p for p in participants if p.in_hand]) <= 1:
                    return

    def _offturn_responses(self, trigger_actor: PlayerState, participants: list[PlayerState], turn: int) -> None:
        if not self.cfg.enable_offturn_self_regulate and not self.cfg.enable_offturn_chatter:
            return
        observers = [
            p
            for p in participants
            if p.player_id != trigger_actor.player_id and p.in_hand and p.lives > 0
        ]
        for observer in observers:
            if self.cfg.enable_offturn_self_regulate:
                self._offturn_self_regulate(observer, trigger_actor, turn)
            if self.cfg.enable_offturn_chatter:
                self._offturn_chatter(observer, trigger_actor, participants, turn)

    def _offturn_self_regulate(self, observer: PlayerState, trigger_actor: PlayerState, turn: int) -> None:
        if observer.focus < 1.0:
            return
        pressure = max(observer.stress / 100.0, observer.emotions.tilt, observer.emotions.fear)
        if pressure < 0.18:
            return
        spend = int(min(observer.focus, max(1.0, 2.0 + pressure * 8.0)))
        if spend <= 0:
            return
        self._commit_focus(observer, spend)
        recover = min(12.0, spend * 0.7 + observer.skill_affect * 0.04)
        observer.stress = clampf(observer.stress - recover, 0.0, 100.0)

        tilt_delta = self._cap_hand_emotion_delta(observer, "tilt", -min(0.10, 0.02 + spend / 320.0), 0.6)
        fear_delta = self._cap_hand_emotion_delta(observer, "fear", -min(0.08, 0.01 + spend / 360.0), 0.6)
        self._apply_single_emotion_delta(observer, "tilt", tilt_delta)
        self._apply_single_emotion_delta(observer, "fear", fear_delta)
        self.event_logger.write(
            "offturn_regulation_resolved",
            {
                "turn": turn,
                "player_id": observer.player_id,
                "trigger_player_id": trigger_actor.player_id,
                "focus_spent": spend,
                "stress_recovered": round(recover, 3),
                "deltas": {
                    "tilt": round(tilt_delta, 4),
                    "fear": round(fear_delta, 4),
                },
                "target_emotions": self._emotion_dict(observer.emotions),
            },
        )

    def _offturn_chatter(
        self, observer: PlayerState, trigger_actor: PlayerState, participants: list[PlayerState], turn: int
    ) -> None:
        if observer.focus < 2.0:
            return
        # Keep extra model load bounded.
        if self.rng.random() > 0.35:
            return
        chat = self._ask_player_for_chatter(observer, participants, turn)
        message = str(chat.get("message", "")).strip()
        if not message:
            return
        target_id = str(chat.get("target_player_id", "")).strip() or trigger_actor.player_id
        target = self._find_player(target_id)
        if target is None or target.player_id == observer.player_id or not target.in_hand:
            target = trigger_actor if trigger_actor.in_hand else None
        if target is None:
            return
        intended = normalize_emotion(str(chat.get("intended_emotion", "fear")))
        tone = str(chat.get("tone", "neutral")).strip().lower()[:24]
        self.event_logger.write(
            "chatter_posted",
            {
                "turn": turn,
                "phase": "offturn",
                "player_id": observer.player_id,
                "target_player_id": target.player_id,
                "trigger_player_id": trigger_actor.player_id,
                "tone": tone or "neutral",
                "intended_emotion": intended,
                "message": message[:180],
            },
        )
        eval_out = self._evaluate_chatter_effect(observer, target, message, intended, turn)
        effect_emotion = normalize_emotion(str(eval_out.get("impact_emotion", intended)))
        raw_delta = clampf(float(eval_out.get("delta", 0.0)), -0.18, 0.18)
        applied = self._cap_hand_emotion_delta(target, effect_emotion, raw_delta, 0.6)
        self._apply_single_emotion_delta(target, effect_emotion, applied)
        target.stress = clampf(target.stress + abs(applied) * 8.0, 0.0, 100.0)
        self.event_logger.write(
            "chatter_evaluated",
            {
                "turn": turn,
                "phase": "offturn",
                "speaker_id": observer.player_id,
                "target_player_id": target.player_id,
                "trigger_player_id": trigger_actor.player_id,
                "impact_emotion": effect_emotion,
                "raw_delta": round(raw_delta, 4),
                "applied_delta": round(applied, 4),
                "summary": str(eval_out.get("summary", ""))[:180],
                "target_emotions": self._emotion_dict(target.emotions),
            },
        )

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
                "card_style": self.card_style,
                "community_cards": list(self.community_cards),
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

        selected_model = self._select_model_for_player(actor)
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
            actor.hand_contribution += commit
            self.pot += commit
        elif action.kind == ActionKind.RAISE:
            raise_amount = int(action.payload.get("amount", self.cfg.min_raise))
            raise_amount = max(self.cfg.min_raise, raise_amount)
            commit = min(actor.bankroll, to_call + raise_amount)
            actor.bankroll -= commit
            actor.current_bet += commit
            actor.hand_contribution += commit
            self.pot += commit
            self.current_high_bet = max(self.current_high_bet, actor.current_bet)
            was_raise = True
            target = self._find_player(action.attack_plan.target_player_id) if action.attack_plan else None
            if target is not None:
                if self.cfg.enable_direct_emoter_attacks:
                    before = self._emotion_dict(target.emotions)
                    self._apply_affective_effects(target, action.attack_plan.emotional_intent.value)
                    self.event_logger.write(
                        "direct_emoter_attack_resolved",
                        {
                            "turn": turn,
                            "attacker_id": actor.player_id,
                            "target_player_id": target.player_id,
                            "emotion": action.attack_plan.emotional_intent.value,
                            "before": before,
                            "after": self._emotion_dict(target.emotions),
                        },
                    )
                else:
                    self.event_logger.write(
                        "direct_emoter_attack_skipped",
                        {
                            "turn": turn,
                            "attacker_id": actor.player_id,
                            "target_player_id": target.player_id,
                            "reason": "disabled_by_config",
                        },
                    )
                actor.tempo += 1
        else:
            if to_call > 0:
                commit = min(to_call, actor.bankroll)
                actor.bankroll -= commit
                actor.current_bet += commit
                actor.hand_contribution += commit
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

    def _showdown(
        self, participants: list[PlayerState]
    ) -> tuple[list[PlayerState], dict[str, dict], dict[str, tuple[int, tuple[int, ...]]]]:
        contenders = [p for p in participants if p.in_hand]
        if len(contenders) == 1:
            only = contenders[0]
            rankings = {only.player_id: {"category": "walk", "score": [99]}}
            powers = {only.player_id: (99, (0,))}
            return [only], rankings, powers

        rankings: dict[str, dict] = {}
        powers: dict[str, tuple[int, tuple[int, ...]]] = {}
        best_score: tuple[int, tuple[int, ...]] | None = None
        winners: list[PlayerState] = []
        for p in contenders:
            if self.card_style == "holdem":
                category, score, name, best_five = evaluate_holdem_hand(p.hand, self.community_cards)
                shown_hand = list(best_five)
            else:
                category, score, name = evaluate_hand(p.hand)
                shown_hand = list(p.hand)
            powers[p.player_id] = (category, score)
            rankings[p.player_id] = {
                "category": name,
                "score": [category, *score],
                "hand": shown_hand,
                "hole_cards": list(p.hand),
            }
            combined = (category, score)
            if best_score is None or combined > best_score:
                best_score = combined
                winners = [p]
            elif combined == best_score:
                winners.append(p)
        return winners, rankings, powers

    def _apply_hand_outcome(
        self,
        participants: list[PlayerState],
        winners: list[PlayerState],
        rankings: dict[str, dict],
        powers: dict[str, tuple[int, tuple[int, ...]]],
        turn: int,
    ) -> None:
        winner_ids = {p.player_id for p in winners}
        payouts = self._compute_side_pots(participants, powers)
        for pid, amount in payouts.items():
            player = self._find_player(pid)
            if player is not None and amount > 0:
                player.bankroll += amount
        winner_ids = {pid for pid, amount in payouts.items() if amount > 0}

        life_losses = 0
        if self.cfg.enable_lives:
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
        else:
            at_risk = [p.player_id for p in participants if p.player_id not in winner_ids and p.in_hand]
            self.event_logger.write(
                "lives_disabled",
                {
                    "turn": turn,
                    "at_risk_players": at_risk,
                },
            )
        self.event_logger.write(
            "showdown",
            {
                "turn": turn,
                "pot": self.pot,
                "winners": list(winner_ids),
                "life_losses": life_losses,
                "payouts": payouts,
                "rankings": rankings,
                "card_style": self.card_style,
                "community_cards": list(self.community_cards),
            },
        )
        self.event_logger.write(
            "hand_ended",
            {
                "turn": turn,
                "card_style": self.card_style,
                "community_cards": list(self.community_cards),
                "players": [self._public_player_state(p) for p in self.players],
            },
        )
        print(
            f"Showdown winners={','.join(sorted(winner_ids))} pot={self.pot} "
            f"losers_life_loss={life_losses}"
        )

    def _compute_side_pots(
        self, participants: list[PlayerState], powers: dict[str, tuple[int, tuple[int, ...]]]
    ) -> dict[str, int]:
        payouts = {p.player_id: 0 for p in participants}
        contributions = {p.player_id: max(0, int(p.hand_contribution)) for p in participants}
        levels = sorted({amt for amt in contributions.values() if amt > 0})
        if not levels:
            return payouts

        prev = 0
        for level in levels:
            layer_contributors = [p for p in participants if contributions[p.player_id] >= level]
            if not layer_contributors:
                prev = level
                continue
            tranche = (level - prev) * len(layer_contributors)
            if tranche <= 0:
                prev = level
                continue

            eligible = [p for p in layer_contributors if p.in_hand and p.player_id in powers]
            if not eligible:
                prev = level
                continue

            best_power: tuple[int, tuple[int, ...]] | None = None
            layer_winners: list[PlayerState] = []
            for p in eligible:
                power = powers[p.player_id]
                if best_power is None or power > best_power:
                    best_power = power
                    layer_winners = [p]
                elif power == best_power:
                    layer_winners.append(p)

            split = tranche // len(layer_winners)
            remainder = tranche % len(layer_winners)
            for i, winner in enumerate(layer_winners):
                payouts[winner.player_id] += split + (1 if i < remainder else 0)
            prev = level
        return payouts

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
        self.available_models = set(available)
        self.model_router.set_available_models(available)
        if available:
            print("Available routed models:")
            for model in available:
                print(f"- {model}")

    def _select_player_avatars(self) -> None:
        for actor in self.players:
            if actor.lives <= 0:
                continue
            actor.avatar_id = self._ask_player_for_avatar(actor)
            self.event_logger.write(
                "avatar_selected",
                {
                    "player_id": actor.player_id,
                    "avatar_id": actor.avatar_id,
                },
            )

    def _ask_player_for_avatar(self, actor: PlayerState) -> str:
        fallback = AVATAR_IDS[(sum(ord(c) for c in actor.player_id) + self.cfg.seed) % len(AVATAR_IDS)]
        model = self._select_model_for_player(actor)
        prompt_state = {
            "player_id": actor.player_id,
            "will": actor.will,
            "skill_affect": actor.skill_affect,
            "available_avatars": AVATAR_IDS,
        }
        self.event_logger.write(
            "thinking",
            {
                "turn": 0,
                "player_id": actor.player_id,
                "status": "start",
                "model": model,
                "stage": "avatar",
            },
        )
        try:
            response = self.client.chat_json(
                system_prompt="Select a single avatar id. Return JSON only.",
                user_prompt=(
                    "Pick avatar_id from available_avatars. "
                    "Schema: {avatar_id, summary}. "
                    f"State: {json.dumps(prompt_state)}"
                ),
                max_tokens=140,
                model=model,
            )
            self.token_monitor.record(actor.player_id, response.model, response.usage)
        except Exception:
            self.event_logger.write(
                "thinking",
                {
                    "turn": 0,
                    "player_id": actor.player_id,
                    "status": "end",
                    "stage": "avatar",
                    "outcome": "provider_failure",
                    "summary": f"fallback_avatar={fallback}",
                },
            )
            return fallback

        parsed = self._parse_json(response.content)
        picked = str(parsed.get("avatar_id", "")).strip()
        if picked not in AVATAR_IDS:
            picked = fallback
        summary = str(parsed.get("summary", "")).strip()[:180]
        self.event_logger.write(
            "provider_call",
            {
                "turn": 0,
                "player_id": actor.player_id,
                "requested_model": model,
                "resolved_model": response.model,
                "latency_ms": response.latency_ms,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "max_output_tokens": 140,
                "stage": "avatar",
            },
        )
        self.event_logger.write(
            "thinking",
            {
                "turn": 0,
                "player_id": actor.player_id,
                "status": "end",
                "stage": "avatar",
                "outcome": "avatar_selected",
                "summary": summary or f"picked={picked}",
            },
        )
        return picked

    def _select_model_for_player(self, actor: PlayerState) -> str:
        assigned = self.player_models.get(actor.player_id.upper())
        if assigned:
            if self.available_models and assigned not in self.available_models:
                self.event_logger.write(
                    "model_assignment_warning",
                    {
                        "player_id": actor.player_id,
                        "assigned_model": assigned,
                        "reason": "assigned_model_not_available",
                    },
                )
            else:
                return assigned
        return self.model_router.pick_action_model(actor_tilt=actor.emotions.tilt, actor_exposure=actor.exposure)

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
            "avatar_id": player.avatar_id,
            "lives": player.lives,
            "bankroll": player.bankroll,
            "current_bet": player.current_bet,
            "hand_contribution": player.hand_contribution,
            "in_hand": player.in_hand,
            "hand": list(player.hand),
            "will": player.will,
            "skill_affect": player.skill_affect,
            "focus": round(player.focus, 3),
            "stress": round(player.stress, 3),
            "resistance_bonus": round(player.resistance_bonus, 3),
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


def evaluate_holdem_hand(hole_cards: list[str], community_cards: list[str]) -> tuple[int, tuple[int, ...], str, tuple[str, ...]]:
    all_cards = list(hole_cards) + list(community_cards)
    if len(all_cards) < 5:
        padded = all_cards + ["2C"] * (5 - len(all_cards))
        category, score, name = evaluate_hand(padded[:5])
        return category, score, name, tuple(padded[:5])
    best_power: tuple[int, tuple[int, ...]] | None = None
    best_name = "high_card"
    best_combo: tuple[str, ...] = tuple(all_cards[:5])
    for combo in combinations(all_cards, 5):
        category, score, name = evaluate_hand(list(combo))
        power = (category, score)
        if best_power is None or power > best_power:
            best_power = power
            best_name = name
            best_combo = tuple(combo)
    assert best_power is not None
    return best_power[0], best_power[1], best_name, best_combo


def clampf(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def normalize_emotion(value: str) -> str:
    v = value.strip().lower()
    if v not in {"fear", "anger", "shame", "confidence", "tilt"}:
        return "fear"
    return v
