# Damage Simulation Design Spec

Version: 0.3 (Implemented Baseline)
Status: Draft

## 1. Scope and Intent
This project implements a playable, simulation-first, poker-like card game inspired by Damage in *Consider Phlebas*: high stakes, emotional manipulation, incomplete information, and social pressure.

The implementation is intentionally not a canon rules reconstruction. It is a coherent ruleset designed for LLM-vs-LLM emergence.

## 2. Implemented Core Rules
- Players: configurable (default 4).
- Hand loop: `deal -> ante -> betting -> showdown -> payouts -> life updates`.
- Cards: standard 52-card deck; each active player receives 5 private cards.
- Betting actions: `fold`, `check`, `call`, `raise`.
- Stakes:
  - Everyone antes chips each hand.
  - Pot is awarded to showdown winner(s).
- Lives:
  - Players who **stay in to showdown and lose** lose 1 Life.
  - Players who **fold** lose chips already committed but do **not** lose a Life.
  - Life 0 eliminates player from future hands.

This preserves the key choice: fold to avoid life risk, or stay in and risk a Life.

## 3. Emotional Manipulation
- Emotional vectors per player:
  - `fear`, `anger`, `shame`, `confidence`, `tilt`.
- Aggressive pressure requirement:
  - `raise` actions must include `attack_plan` with emotional target intent.
- Emotional update is applied on successful pressure actions and affects future routing/behavior.

## 4. LLM Decision Contract
Each actor receives public table state and private hand state and returns JSON:
- `kind`: one of `fold|check|call|raise`
- `payload`: includes `amount` for raises
- `attack_plan`: required for `raise`
- `reasoning_summary`: short observer-facing summary

Invalid outputs are coerced to legal fallback actions.

## 5. Implemented Hand Evaluation
Showdown ranking (high to low):
- straight flush
- four of a kind
- full house
- flush
- straight
- three of a kind
- two pair
- pair
- high card

## 6. Runtime Telemetry
- Per-call token usage captured and aggregated.
- Required context capacity estimated from rolling usage (`p95` based heuristic).
- Context warnings emitted when utilization approaches/exceeds configured window.

## 7. Event Stream (Implemented)
Core events emitted to JSONL:
- `game_started`
- `hand_started`
- `phase_changed`
- `thinking` (start/end + summary)
- `provider_call`
- `action_submitted`
- `action_resolved`
- `fold_saved_life`
- `life_lost`
- `player_eliminated`
- `showdown`
- `hand_ended`
- `turn_summary`
- `game_ended`

## 8. Visualizer Alignment
Live/replay visualizer currently renders:
- table status (`turn`, `pot`, `high_bet`, winners)
- per-player cards and betting state
- all tracked emotions
- live `thinking...` badge and latest thought summary
- colorized JSON event feed

## 9. Known Gaps
- No canonical betting rounds/street system yet (single simplified betting cycle with limited passes).
- No hidden/public separation in browser roles yet (current visualizer is dev/research oriented).
- No persistent DB backend yet (JSONL event logs only).
