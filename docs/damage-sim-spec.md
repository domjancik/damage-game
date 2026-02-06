# Damage Simulation Design Spec

Version: 0.3 (Implemented Baseline)
Status: Draft

## 1. Scope and Intent
This project implements a playable, simulation-first, poker-like card game inspired by Damage in *Consider Phlebas*: high stakes, emotional manipulation, incomplete information, and social pressure.

The implementation is intentionally not a canon rules reconstruction. It is a coherent ruleset designed for LLM-vs-LLM emergence.

## 2. Implemented Core Rules
- Players: configurable (default 4).
- Hand loop: `deal -> ante -> affect -> betting -> showdown -> payouts -> life updates`.
- Cards: standard 52-card deck; each active player receives 5 private cards.
  - configurable via `card_style`:
    - `draw5`: each active player receives 5 private cards.
    - `holdem`: each active player receives 2 private hole cards plus 5 community cards on board.
- Betting actions: `fold`, `check`, `call`, `raise`.
- Stakes:
  - Everyone antes chips each hand.
  - Pot is awarded to showdown winner(s).
- Lives:
  - Players who **stay in to showdown and lose** lose 1 Life.
  - Players who **fold** lose chips already committed but do **not** lose a Life.
  - Life 0 eliminates player from future hands.
  - Side-pot payouts are used for uneven all-ins.
  - configurable via `enable_lives` for pure-chip mode.

This preserves the key choice: fold to avoid life risk, or stay in and risk a Life.

## 3. Emotional Manipulation
- Emotional vectors per player:
  - `fear`, `anger`, `shame`, `confidence`, `tilt`.
- Affect contest stats:
  - `will`, `skill_affect`, `focus`, `stress`, `resistance_bonus`.
- Affect phase actions:
  - `attack`, `assist`, `guard`, `self_regulate`, `none`.
- Optional discussion/chatter layer:
  - if enabled, each actor can post short social pressure chatter and target players evaluate emotional effect.
- Cooperation:
  - Assist effects use diminishing returns and hard cap on team power.
- Bounds:
  - per-event emotional delta clamp and per-hand cumulative cap.
- Aggressive pressure requirement:
  - `raise` actions must include `attack_plan` with emotional target intent.
- Emotional update is applied on successful pressure actions and affects future routing/behavior.
- Direct raise-triggered emotional effects can be disabled via `enable_direct_emoter_attacks`.

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

Hold'em mode uses best 5-card combination from 7 cards (`2 hole + 5 community`).

## 6. Runtime Telemetry
- Per-call token usage captured and aggregated.
- Required context capacity estimated from rolling usage (`p95` based heuristic).
- Context warnings emitted when utilization approaches/exceeds configured window.
- Per-player model assignment supported (`P1=...` style mapping) with availability fallback warnings.

## 7. Event Stream (Implemented)
Core events emitted to JSONL:
- `game_started`
- `hand_started`
- `phase_changed`
- `thinking` (start/end + summary)
- `affect_intent`
- `affect_resolved`
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
- `chatter_posted`
- `chatter_evaluated`
- `direct_emoter_attack_resolved`
- `direct_emoter_attack_skipped`
- `lives_disabled`

## 8. Visualizer Alignment
Live/replay visualizer currently renders:
- table status (`turn`, `pot`, `high_bet`, winners)
- per-player cards and betting state
- all tracked emotions
- live `thinking...` badge and latest thought summary
- colorized JSON event feed
- pixel top-view table visualizer with procedural sprites and replay speed controls (`/table`).

## 9. Known Gaps
- No canonical betting rounds/street system yet (single simplified betting cycle with limited passes).
- No hidden/public separation in browser roles yet (current visualizer is dev/research oriented).
- No persistent DB backend yet (JSONL event logs only).
