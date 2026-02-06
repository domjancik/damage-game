from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    PLAY_CARD = "play_card"
    ACTIVATE = "activate"
    SPEAK = "speak"
    PASS = "pass"
    REACTION = "reaction"


class KineticIntent(str, Enum):
    DISCARD_PRESSURE = "discard_pressure"
    LOCKOUT = "lockout"
    COMBO_BREAK = "combo_break"
    TEMPO_SWING = "tempo_swing"
    FORCED_LINE = "forced_line"


class EmotionalIntent(str, Enum):
    FEAR = "fear"
    ANGER = "anger"
    SHAME = "shame"
    TILT = "tilt"
    OVERCONFIDENCE = "overconfidence"
    PARANOIA = "paranoia"


class ManipulationPlan(str, Enum):
    THREAT_FRAMING = "threat_framing"
    BAIT = "bait"
    FALSE_CONCESSION = "false_concession"
    PUBLIC_ISOLATION = "public_isolation"
    STATUS_CHALLENGE = "status_challenge"
    BETRAYAL_CUE = "betrayal_cue"


class DeliveryChannel(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    MIXED = "mixed"


@dataclass(slots=True)
class AttackPlan:
    kinetic_intent: KineticIntent
    emotional_intent: EmotionalIntent
    manipulation_plan: ManipulationPlan
    delivery_channel: DeliveryChannel
    target_player_id: str
    expected_behavior_shift: str
    confidence: float

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> "AttackPlan":
        def parse_enum(enum_cls: type[Enum], value: Any, default: Enum) -> Enum:
            if isinstance(value, enum_cls):
                return value
            text = str(value or "").strip().lower()
            try:
                return enum_cls(text)
            except Exception:
                normalized = text.replace(" ", "_").replace("-", "_")
                for member in enum_cls:
                    name = member.value.lower()
                    if name == normalized or name in normalized or normalized in name:
                        return member
            return default

        confidence = float(obj.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return cls(
            kinetic_intent=parse_enum(
                KineticIntent, obj.get("kinetic_intent"), KineticIntent.DISCARD_PRESSURE
            ),
            emotional_intent=parse_enum(EmotionalIntent, obj.get("emotional_intent"), EmotionalIntent.FEAR),
            manipulation_plan=parse_enum(
                ManipulationPlan, obj.get("manipulation_plan"), ManipulationPlan.THREAT_FRAMING
            ),
            delivery_channel=parse_enum(DeliveryChannel, obj.get("delivery_channel"), DeliveryChannel.PUBLIC),
            target_player_id=str(obj["target_player_id"]),
            expected_behavior_shift=str(obj["expected_behavior_shift"]),
            confidence=confidence,
        )


@dataclass(slots=True)
class ActionEnvelope:
    player_id: str
    kind: ActionKind
    payload: dict[str, Any] = field(default_factory=dict)
    attack_plan: AttackPlan | None = None
    reasoning_summary: str = ""

    @classmethod
    def from_obj(cls, obj: dict[str, Any], player_id: str) -> "ActionEnvelope":
        kind = ActionKind(obj.get("kind", "pass"))
        attack_plan = None
        if isinstance(obj.get("attack_plan"), dict):
            try:
                attack_plan = AttackPlan.from_obj(obj["attack_plan"])
            except Exception:
                attack_plan = None
        return cls(
            player_id=player_id,
            kind=kind,
            payload=dict(obj.get("payload", {})),
            attack_plan=attack_plan,
            reasoning_summary=str(obj.get("reasoning_summary", "")),
        )


@dataclass(slots=True)
class EmotionState:
    fear: float = 0.0
    anger: float = 0.0
    shame: float = 0.0
    confidence: float = 0.0
    tilt: float = 0.0


@dataclass(slots=True)
class PlayerState:
    player_id: str
    lives: int = 3
    resolve: int = 12
    tempo: int = 0
    exposure: int = 0
    emotions: EmotionState = field(default_factory=EmotionState)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class ProviderResponse:
    content: str
    usage: Usage
    model: str
    latency_ms: float


class ActionValidationError(ValueError):
    pass


def validate_action(action: ActionEnvelope) -> None:
    is_attack = action.kind in {ActionKind.PLAY_CARD, ActionKind.ACTIVATE, ActionKind.REACTION}
    if not is_attack:
        return

    is_non_trivial = bool(action.payload.get("non_trivial", True))
    if is_non_trivial and action.attack_plan is None:
        raise ActionValidationError("non-trivial attack actions require attack_plan")
