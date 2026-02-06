# Implementation Status

Version: 0.1
Updated: 2026-02-06

## 1. Implemented Features
- Poker-like hand loop with stakes:
  - `deal -> ante -> affect -> betting -> showdown`
  - card styles: `draw5` and `holdem` (2 hole + 5 community)
  - `fold/check/call/raise` actions
  - side-pot split payouts for uneven all-ins
  - life loss only for players who stay in and lose showdown
- Emotional mechanics:
  - per-player vectors: `fear/anger/shame/confidence/tilt`
  - bounded affect stats: `will/skill_affect/focus/stress/resistance_bonus`
  - affect modes: `attack`, `assist`, `guard`, `self_regulate`, `none`
  - cooperation with caps/diminishing returns
  - direct assist fallback (`assist_direct`) for unpaired assists
  - optional discussion/chatter layer (`chatter_posted` + `chatter_evaluated`)
  - configurable direct raise-triggered emotional effects (`enable_direct_emoter_attacks`)
- Rule toggles:
  - `enable_lives`
  - `enable_direct_emoter_attacks`
  - `enable_discussion_layer`
  - profile presets (`damage-game`, `poker-texasholdem`) with optional JSON overrides
- LLM runtime:
  - OpenAI-compatible client (LM Studio target)
  - model fallback routing
  - per-player model assignment (`P1=...`) with warning/fallback
  - robust parsing fallback for malformed/null payloads
- Tournament runtime:
  - `damage_game.tournament_cli` for multi-round progression
  - 6-max or 8-max table assignment
  - per-table advancement (`advance_per_table`) with escalating ante tiers
  - tournament event log (`tournament_*.events.jsonl`) including table spawn/results
- Observability:
  - JSONL event log per game under `runs/`
  - per-call usage + context-capacity estimation
  - replay CLI and live tail support
- Visualizers:
  - dashboard view (`/`) with replay cursor controls and event feed
  - pixel top-view table (`/table`) with procedural sprites, cards, HUD, replay speed slider
  - 3D arena preview (`/arena`) showing multiple game tables, stake-height pyramid layout, and seat avatars
- Avatar identity:
  - per-player `avatar_selected` event at game start
  - avatar id propagated through player snapshots

## 2. Event Coverage (Current)
- core:
  - `game_started`, `hand_started`, `phase_changed`, `showdown`, `hand_ended`, `game_ended`
- tournament:
  - `tournament_started`, `round_started`, `table_spawned`, `table_result`, `round_ended`, `tournament_ended`
- actions:
  - `action_submitted`, `action_resolved`, `action_rejected`
- affect:
  - `affect_intent`, `affect_resolved`, `affect_unpaired_assist`
- model/runtime:
  - `thinking`, `provider_call`, `model_assignment_warning`
- identity:
  - `avatar_selected`
- stakes:
  - `fold_saved_life`, `life_lost`, `player_eliminated`
- telemetry:
  - `turn_summary`

## 3. Current CLI Surface
- simulation: `uv run --python 3.11 -m damage_game.cli`
- tournament: `uv run --python 3.11 -m damage_game.tournament_cli`
- replay list/play: `uv run --python 3.11 -m damage_game.replay_cli`
- visualizer server: `uv run --python 3.11 -m damage_game.visualizer_cli`
- per-player model assignment:
  - `--player-models "P1=modelA,P2=modelB,..."`

## 4. Not Yet Implemented
- spectator-safe redaction roles in web UI
- persistent DB backend (currently JSONL)
- formal multi-street poker variant/community cards
- test suite coverage for all event contracts and side-pot edge cases
- 3D arena page (Three.js) with multi-table tournament projection
- tournament progression service (6-max/8-max bracket advancement)
- avatar selection and procedural expression mapping in 3D scene
- authenticated user onboarding and encrypted provider endpoint vault

## 5. Recommended Next Docs
- `docs/testing-strategy.md`:
  - deterministic seeds, golden log comparisons, side-pot/property tests
- `docs/modeling-playbook.md`:
  - recommended player-model mixes and cost/latency profiles
- `docs/redaction-and-roles.md`:
  - public/research/admin visibility boundaries
- `docs/threejs-tournament-platform-spec.md`:
  - 3D arena UX, multi-table topology, tournament lifecycle, auth + secret handling
