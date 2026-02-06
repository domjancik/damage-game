# Schema Specification

Version: 0.2 (Implemented Baseline)
Status: Draft

## 1. Purpose
Define canonical JSON payloads currently produced/consumed by the simulator, replay tooling, and visualizer.

## 2. Envelope
All persisted events are JSONL lines with:
- `schema_version: string`
- `type: string`
- `game_id: string`
- `ts: ISO8601 UTC string`
- `payload: object`

## 3. Player State
## 3.1 EmotionState
- `fear: float` in `[-1,1]`
- `anger: float` in `[-1,1]`
- `shame: float` in `[-1,1]`
- `confidence: float` in `[-1,1]`
- `tilt: float` in `[-1,1]`

## 3.2 PlayerPublicState
- `player_id: string`
- `lives: int`
- `bankroll: int`
- `current_bet: int`
- `in_hand: bool`
- `hand: string[]` (5 card codes, for current dev visualizer)
- `will: int`
- `skill_affect: int`
- `focus: float`
- `stress: float`
- `resistance_bonus: float`
- `tempo: int`
- `exposure: int`
- `emotions: EmotionState`

## 4. Action Schemas
## 4.1 ActionEnvelope
- `player_id: string`
- `kind: enum[fold, check, call, raise, pass]`
- `payload: object`
- `reasoning_summary: string`
- `attack_plan: AttackPlan|null`

## 4.2 AttackPlan (required for `raise`)
- `kinetic_intent: enum[discard_pressure, lockout, combo_break, tempo_swing, forced_line]`
- `emotional_intent: enum[fear, anger, shame, tilt, overconfidence, paranoia]`
- `manipulation_plan: enum[threat_framing, bait, false_concession, public_isolation, status_challenge, betrayal_cue]`
- `delivery_channel: enum[public, private, mixed]`
- `target_player_id: string`
- `expected_behavior_shift: string`
- `confidence: float` in `[0,1]`

Validation:
- if `kind == raise`, `attack_plan` is required
- if `kind == raise`, `payload.amount` must be integer `> 0`

## 5. Event Payloads (Implemented)
## 5.1 `game_started`
- `players: int`
- `turns: int`
- `primary_model: string`
- `fallback_models: string[]`
- `seed: int`

## 5.2 `hand_started`
- `turn: int`
- `pot: int`
- `ante: int`
- `players: PlayerPublicState[]`

## 5.3 `phase_changed`
- `turn: int`
- `phase: enum[affect, betting, showdown]`

## 5.4 `thinking`
- `turn: int`
- `player_id: string`
- `status: enum[start, end]`
- `stage?: enum[affect]` (present for affect phase thinking calls)
- `model?: string` (present on start)
- `outcome?: string` (present on end)
- `summary?: string` (short thought summary, present on successful end)

## 5.5 `affect_intent`
- `turn: int`
- `player_id: string`
- `intent: {mode, focus_spend, target_player_id, lead_player_id, emotion, summary}`

## 5.6 `affect_resolved`
- `turn: int`
- `mode: enum[guard, attack_team, assist_direct, self_regulate]`
- `player_id?: string` (guard actor)
- `lead_player_id?: string` (team attack lead)
- `assistants?: string[]`
- `target_player_id?: string`
- `emotion?: string`
- `focus_spent?: int`
- `resistance_bonus?: float`
- `team_power?: float`
- `attack_score?: float`
- `defense_score?: float`
- `raw_delta?: float`
- `applied_delta?: float`
- `stake_multiplier?: float`
- `target_emotions?: EmotionState`
- `deltas?: map[emotion -> float]` (self-regulation summary)
- `stress_recovered?: float`

## 5.7 `provider_call`
- `turn: int`
- `player_id: string`
- `requested_model: string`
- `resolved_model: string`
- `latency_ms: float`
- `usage: {prompt_tokens:int, completion_tokens:int, total_tokens:int}`
- `max_output_tokens: int`

## 5.8 `action_submitted`
- `turn: int`
- `player_id: string`
- `action: ActionEnvelope`

## 5.9 `action_resolved`
- `turn: int`
- `player_id: string`
- `kind: string`
- `pot: int`
- `current_high_bet: int`
- `player_state: PlayerPublicState`
- `attack_plan: AttackPlan|null`

## 5.10 `fold_saved_life`
- `turn: int`
- `player_id: string`

## 5.11 `life_lost` / `player_eliminated`
- `turn: int`
- `player_id: string`
- `remaining_lives: int`

## 5.12 `showdown`
- `turn: int`
- `pot: int`
- `winners: string[]`
- `life_losses: int`
- `payouts: map[player_id -> int]`
- `rankings: map[player_id -> {category:string, score:int[], hand?:string[]}]`

## 5.13 `hand_ended`
- `turn: int`
- `players: PlayerPublicState[]`

## 5.14 `turn_summary`
- `turn: int`
- `token_stats: {calls, avg_prompt, avg_completion, avg_total, p95_total, required_context_capacity}`
- `token_stats_by_model: map[model -> same stats subset]`
- `context_warning: string|null`

## 5.15 `game_ended`
- `final_state: PlayerPublicState[]`
- `token_stats: object`
- `token_stats_by_model: object`

## 5.16 `model_assignment_warning`
- `player_id: string`
- `assigned_model: string`
- `reason: string`

## 5.17 `affect_unpaired_assist`
- `turn: int`
- `assistant_id: string`
- `target_player_id: string`
- `emotion: string`
- `outcome: string`

## 6. Replay/Visualizer API Contracts
- `GET /api/games` -> `{games:[{game_id,event_count,modified_ts}]}`
- `GET /api/replay?game_id=...` -> `{game_id,events:[...envelopes]}`
- `GET /api/stream?game_id=...` -> SSE stream of event envelopes

## 7. Notes
- Current visualizer is a dev/research surface and intentionally renders private cards.
- Future role-gated redaction should hide `hand` and thought summaries for spectator mode.
