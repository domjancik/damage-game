# Schema Specification

Version: 0.1
Status: Draft

## 1. Purpose
Define canonical schemas for game state, actions, emotional modeling, events, and provider I/O.

## 2. Conventions
- Encoding: JSON UTF-8.
- IDs: opaque strings (`game_...`, `evt_...`, `plr_...`).
- Timestamps: ISO8601 UTC.
- Numeric ranges:
  - emotion values in `[-1.0, 1.0]`
  - probabilities in `[0.0, 1.0]`

## 3. Core Domain Schemas
## 3.1 WorldState
- `game_id: string`
- `seed: int`
- `turn: int`
- `phase: enum[upkeep, draw, intent, talk, action, resolve, reflect, end]`
- `players: PlayerPublicState[]`
- `arena: ArenaState`
- `discard: CardRef[]`
- `initiative_order: string[]`
- `rule_flags: object`

## 3.2 PlayerPublicState
- `player_id: string`
- `display_name: string`
- `alive: bool`
- `lives: int`
- `resolve: int`
- `tempo: int`
- `exposure: int`
- `hand_count: int`
- `arena_cards: CardRef[]`

## 3.3 PlayerPrivateState
- `player_id: string`
- `hand: CardRef[]`
- `secret_plan: SecretPlan|null`
- `memory_state: MemoryState`
- `emotion_state: EmotionState`
- `belief_state: BeliefState`

## 3.4 EmotionState
- `valence: float`
- `arousal: float`
- `dominance: float`
- `fear: float`
- `anger: float`
- `shame: float`
- `confidence: float`
- `greed: float`
- `tilt: float`
- `trust: map[player_id -> float]`
- `grievance: map[player_id -> float]`

## 3.5 CardRef
- `card_id: string`
- `name: string`
- `type: enum[gambit, guard, trap, mask, pressure, ritual]`
- `tags: string[]`

## 4. Action Schemas
## 4.1 ActionEnvelope
- `action_id: string`
- `game_id: string`
- `turn: int`
- `phase: string`
- `player_id: string`
- `kind: enum[play_card, activate,speak,pass,reaction]`
- `payload: object`
- `submitted_at: string`

## 4.2 AttackPlan (required for non-trivial attacks)
- `kinetic_intent: enum[discard_pressure, lockout, combo_break, tempo_swing, forced_line]`
- `emotional_intent: enum[fear, anger, shame, tilt, overconfidence, paranoia]`
- `manipulation_plan: enum[threat_framing, bait, false_concession, public_isolation, status_challenge, betrayal_cue]`
- `delivery_channel: enum[public, private, mixed]`
- `target_player_id: string`
- `expected_behavior_shift: string`
- `confidence: float`

Validation:
- if `kind` implies attack and `AttackPlan` missing -> reject action.

## 4.3 SpeechActionPayload
- `channel: enum[public, private]`
- `target_player_id: string|null`
- `text: string`
- `speech_act: enum[threat, promise, bluff, warning, concession, taunt, neutral]`

## 5. Resolution Schemas
## 5.1 ResolutionEvent
- `event_id: string`
- `game_id: string`
- `turn: int`
- `phase: string`
- `action_id: string`
- `actor_player_id: string`
- `target_player_ids: string[]`
- `tactical_effect: TacticalEffect`
- `affective_effect: AffectiveEffect`
- `rules_notes: string[]`

## 5.2 TacticalEffect
- `resolve_delta: map[player_id -> int]`
- `tempo_delta: map[player_id -> int]`
- `exposure_delta: map[player_id -> int]`
- `card_moves: CardMove[]`
- `triggered_effects: string[]`

## 5.3 AffectiveEffect
- `emotion_delta: map[player_id -> EmotionDelta>`
- `trust_delta: map[player_id -> map[player_id -> float]>`
- `grievance_delta: map[player_id -> map[player_id -> float]>`
- `manipulation_success: bool`
- `observed_behavior_shift: string|null`

## 6. Event Stream Schemas
Common envelope:
- `type: string`
- `event_id: string`
- `game_id: string`
- `turn: int`
- `phase: string`
- `ts: string`
- `payload: object`

Types:
- `game_started`
- `phase_changed`
- `speech_posted`
- `action_submitted`
- `action_rejected`
- `action_resolved`
- `emotion_updated`
- `player_eliminated`
- `game_ended`

## 7. Agent and Provider I/O Schemas
## 7.1 TurnPlanRequest
- `player_private_view: object`
- `public_world_view: object`
- `legal_actions: object[]`
- `constraints: object`

## 7.2 TurnPlanResponse
- `selected_action: ActionEnvelope`
- `attack_plan: AttackPlan|null`
- `speech_actions: SpeechActionPayload[]`
- `self_estimated_emotion_impact: EmotionDelta`
- `confidence: float`

## 7.3 ReflectionRecord
- `player_id: string`
- `turn: int`
- `prediction_accuracy: float`
- `manipulation_outcome: enum[success, partial, failed]`
- `memory_updates: string[]`

## 8. Persistence Model
Minimum tables/collections:
- `games`
- `snapshots`
- `events`
- `actions`
- `agent_traces`
- `provider_calls`

Indexes:
- `(game_id, event_id)` unique
- `(game_id, turn, phase)`
- `(game_id, player_id, turn)`

## 9. Versioning
- Every payload includes `schema_version`.
- Backward-compatible additions only in minor version.
- Breaking changes require migration + major version increment.

## 10. Validation and Testing
- Pydantic models as source of truth.
- Reject unknown enum values unless feature flag permits.
- Property tests for event replay determinism.
- Contract tests for provider output coercion and fallback behavior.

## 11. Acceptance Criteria
- Engine accepts only schema-valid actions/events.
- Replays can be reconstructed from `events` + periodic snapshots.
- Attack actions consistently carry emotional manipulation metadata.
- Visualizer contract consumes stream without custom per-event parsing hacks.
