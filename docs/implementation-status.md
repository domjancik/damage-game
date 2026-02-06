# Implementation Status

Version: 0.1
Updated: 2026-02-06

## 1. Implemented Features
- Poker-like hand loop with stakes:
  - `deal -> ante -> affect -> betting -> showdown`
  - `fold/check/call/raise` actions
  - side-pot split payouts for uneven all-ins
  - life loss only for players who stay in and lose showdown
- Emotional mechanics:
  - per-player vectors: `fear/anger/shame/confidence/tilt`
  - bounded affect stats: `will/skill_affect/focus/stress/resistance_bonus`
  - affect modes: `attack`, `assist`, `guard`, `self_regulate`, `none`
  - cooperation with caps/diminishing returns
  - direct assist fallback (`assist_direct`) for unpaired assists
- LLM runtime:
  - OpenAI-compatible client (LM Studio target)
  - model fallback routing
  - per-player model assignment (`P1=...`) with warning/fallback
  - robust parsing fallback for malformed/null payloads
- Observability:
  - JSONL event log per game under `runs/`
  - per-call usage + context-capacity estimation
  - replay CLI and live tail support
- Visualizers:
  - dashboard view (`/`) with replay cursor controls and event feed
  - pixel top-view table (`/table`) with procedural sprites, cards, HUD, replay speed slider

## 2. Event Coverage (Current)
- core:
  - `game_started`, `hand_started`, `phase_changed`, `showdown`, `hand_ended`, `game_ended`
- actions:
  - `action_submitted`, `action_resolved`, `action_rejected`
- affect:
  - `affect_intent`, `affect_resolved`, `affect_unpaired_assist`
- model/runtime:
  - `thinking`, `provider_call`, `model_assignment_warning`
- stakes:
  - `fold_saved_life`, `life_lost`, `player_eliminated`
- telemetry:
  - `turn_summary`

## 3. Current CLI Surface
- simulation: `uv run --python 3.11 -m damage_game.cli`
- replay list/play: `uv run --python 3.11 -m damage_game.replay_cli`
- visualizer server: `uv run --python 3.11 -m damage_game.visualizer_cli`
- per-player model assignment:
  - `--player-models "P1=modelA,P2=modelB,..."`

## 4. Not Yet Implemented
- spectator-safe redaction roles in web UI
- persistent DB backend (currently JSONL)
- formal multi-street poker variant/community cards
- test suite coverage for all event contracts and side-pot edge cases

## 5. Recommended Next Docs
- `docs/testing-strategy.md`:
  - deterministic seeds, golden log comparisons, side-pot/property tests
- `docs/modeling-playbook.md`:
  - recommended player-model mixes and cost/latency profiles
- `docs/redaction-and-roles.md`:
  - public/research/admin visibility boundaries
