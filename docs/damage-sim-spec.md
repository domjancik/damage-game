# Damage Simulation Design Spec

Version: 0.2 (Damage-inspired)
Status: Draft

## 1. Scope and Intent
This project defines a playable, simulation-first card game inspired by Damage in *Consider Phlebas*: high-stakes, incomplete information, emotional manipulation as a core mechanic, and social pressure shaping rationality.

The goal is not canon reconstruction (the novel keeps formal rules vague). The goal is a coherent ruleset that preserves the same design principles and supports emergent emotionally-intelligent LLM agents.

## 2. Design Principles (Hard Requirements)
1. Psychology-first play: every non-trivial action must include tactical and emotional intent.
2. Incomplete information: hidden hands, uncertain plans, noisy belief updates.
3. Social channel matters: private/public speech changes emotional impact and reputation.
4. Emotional carryover: affect persists and biases future decisions.
5. Affect-driven errors: panic, tilt, overconfidence must increase suboptimal play probability.
6. Bounded agents: no perfect-reasoning omniscience; limited planning depth and noisy inference.
7. High stakes: elimination pressure creates meaningful risk tradeoffs.

## 3. Game Overview
- Players: 4-6 (MVP: 4)
- Format: turn-based rounds until one player remains or round cap is reached.
- Core objective: survive and dominate by reducing opponents' `Resolve` to 0.
- Thematic stakes: each player has `Lives` (integer stakes). Losing at 0 Resolve costs 1 Life and resets Resolve; losing all Lives eliminates player.

## 4. Components
- Shared deck: 120 cards.
- Player deck: all players draw from shared deck (single-deck arena model).
- Zones:
  - Hand (hidden)
  - Arena (public, active effects)
  - Discard (public)
  - Secret Plan (face-down commitment, revealed later)
- Counters:
  - `Resolve` (mental stability in current bout)
  - `Lives` (elimination stakes)
  - `Tempo` (initiative pressure)
  - `Exposure` (how punishable a player is this round)

## 5. Card Types
1. `Gambit`
- Direct tactical pressure: force discard, tax options, break setups.

2. `Guard`
- Defense/counter windows against Gambits and Traps.

3. `Trap`
- Conditional punishers triggered by specific opponent behaviors.

4. `Mask`
- Information manipulation: conceal intent, spoof strength, alter reveal timing.

5. `Pressure`
- Emotional leverage effects tied to speech channel and trust context.

6. `Ritual`
- Slow-build engine cards requiring setup across turns.

## 6. Turn Structure
1. Upkeep
- Resolve drift toward baseline.
- Ongoing card effects tick.

2. Draw
- Draw 2 cards.

3. Intent Commit (required)
- Each player privately submits:
  - `tactical_intent`
  - `emotional_intent` (target emotion and target player)
  - optional `deception_frame`

4. Table Talk Window
- Players may send public statements and one private message.
- Statements are game objects with channel metadata.

5. Action Window
- In initiative order, each player performs up to 2 actions:
  - play card
  - activate arena effect
  - pass
- Reaction windows allow Guards/Traps.

6. Reveal/Resolution
- Secret Plans reveal.
- Tactical effects resolve.
- Emotional effects resolve via appraisal model.

7. Reflection/Update
- Trust/grievance matrices update.
- Emotion vectors decay + apply deltas.
- Tempo and Exposure recomputed.

## 7. Core Mechanics
### 7.1 Resolve and Lives
- Start: `Resolve=12`, `Lives=3`.
- If Resolve <= 0 at end of round:
  - lose 1 Life
  - Resolve reset to 8
  - discard hand, draw 4
- Life reaches 0 -> eliminated.

### 7.2 Tempo
- Represents initiative and table control.
- Gain Tempo via successful Gambits, correct reads, and punished bluffs.
- Tempo grants tie-break and some card thresholds.

### 7.3 Exposure
- Represents immediate vulnerability.
- Increases when overextending, failed bluffs, predictable sequencing.
- High Exposure amplifies incoming tactical and emotional damage.

### 7.4 Hidden Commitment
- Intent Commit is binding metadata used by engine evaluation.
- Certain cards reward alignment between declared emotional intent and execution.

## 8. Attack Model (Mandatory Emotional Manipulation)
Every non-trivial attack action must specify:
- `kinetic_intent`: card-state objective (discard, lockout, combo break, tempo swing)
- `emotional_intent`: desired affect shift (`fear`, `anger`, `shame`, `tilt`, `overconfidence`, `paranoia`)
- `manipulation_plan`: tactic (`threat framing`, `bait`, `false concession`, `public isolation`, `status challenge`, `betrayal cue`)
- `delivery_channel`: `public`, `private`, `mixed`
- `expected_behavior_shift`: predicted opponent behavior next 1-2 turns

Engine output for attack resolution:
- `tactical_effect`: card-state and counters impact
- `affective_effect`: emotion vector delta + trust/reputation updates

Validation rule:
- Missing emotional plan on non-trivial attacks -> invalid action, one reprompt, then forced `pass`.

## 9. Emotional State Model
Per player:
- `E_self`: continuous vector in [-1,1]
  - `valence`, `arousal`, `dominance`
  - `fear`, `anger`, `shame`, `confidence`, `greed`, `tilt`
- `E_other[i]`: estimate of each opponent's emotional state
- `Trust[i]`, `Grievance[i]`

Update equation per round:
`E_t+1 = clamp(decay * E_t + event_impact + social_impact + personality_bias, -1, 1)`

Suggested defaults:
- `decay=0.82`
- `shock_cap=0.45`
- `social_multiplier=0.25`

Behavioral coupling:
- high `fear` -> defensive sequencing, Guard priority
- high `anger` -> punitive targeting, reduced concession
- high `tilt` -> lower expected value line selection
- high `overconfidence` -> bluff overuse, weak risk accounting

## 10. Social and Speech Mechanics
- Public speech modifies table-wide reputation and third-party beliefs.
- Private speech has stronger single-target affect impact but lower reputation effect.
- Contradictions (speech vs action) increase `Exposure` and `Grievance`.
- Repeated accurate warnings increase future credibility (reduces bluff success against that speaker).

## 11. LLM Agent Architecture
1. Perception
- Build player-local state view and uncertainty map.

2. Appraisal
- Convert events/speech into emotion deltas.

3. Deliberation
- Generate candidate lines with expected tactical and affective outcomes.

4. Dialogue
- Produce channel-specific utterances.

5. Action Selection
- Emit strict JSON action schema.

6. Reflection
- Score prediction accuracy, update memory summaries.

Output requirements:
- JSON schema constrained
- no free-form illegal actions
- include confidence and fallback move

## 12. Provider Abstraction
Use LiteLLM as primary router.

Required providers:
- OpenAI API
- OpenRouter
- Ollama
- LM Studio via OpenAI-compatible endpoint

Note:
- Chat subscription/Codex access is not a guaranteed API entitlement; runtime must assume explicit API credentials or local endpoint config.

Provider contract:
- `generate_turn_plan(player_view, schema)`
- `generate_dialogue(context, channel, target?)`
- `generate_reflection(history_slice, outcome)`

Operational requirements:
- retries/timeouts
- per-turn token budget
- model fallback chain
- structured output validation

## 13. Data Schemas (Minimum)
- `WorldState`
- `PlayerPublicState`
- `PlayerPrivateState`
- `EmotionState`
- `AttackPlan`
- `ActionEnvelope`
- `ResolutionEvent`
- `RoundTranscript`

## 14. Metrics and Evaluation
Primary:
- win rate by model/personality
- manipulation success rate
- forced error rate (opponent EV drop after manipulation)
- emotional prediction accuracy
- anti-tilt resilience
- coalition disruption rate

Secondary:
- latency/cost per provider
- invalid action rate
- reprompt frequency

## 15. MVP Milestones
1. Deterministic card engine and resolver.
2. Full rules implementation for 4-player mode.
3. Emotion/trust model integrated into resolution.
4. LLM seat driver with LiteLLM routing.
5. Tournament runner with fixed seeds.
6. Replay logs with prompts/actions/emotion traces.

## 16. Acceptance Criteria
- Each meaningful attack includes an emotional manipulation plan.
- Emotional state measurably changes future tactical choices.
- At least 3 providers interchangeable without engine code changes.
- Replays deterministic given seed and recorded model outputs.
- Metrics show non-random variance in manipulation and resilience.
