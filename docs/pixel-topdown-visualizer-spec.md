# Pixel Top-View Visualizer Spec

Version: 0.1
Status: Draft

## 1. Purpose
Provide a second, game-like visualizer focused on spatial readability and mood:
- top-view table layout
- pixelated player sprites
- visible card hands
- live/replay event sync

## 2. UX Goals
- Make state legible at a glance: who is in-hand, stacked, stressed, winning.
- Present players as distinct agents via deterministic sprite traits.
- Keep event-driven playback deterministic and auditable.

## 3. View Model
- Table center:
  - pot
  - high bet
  - current turn
  - winner chips
- Seats around oval:
  - player label
  - life, bankroll, current bet
  - emotional summary
  - 5-card row
  - pixel sprite

## 4. Sprite Design
- 16x16 pixel sprite rendered in `<canvas>`, scaled with `image-rendering: pixelated`.
- Deterministic trait mapping from player state:
  - skin/base tone from `player_id` hash
  - jacket color influenced by `skill_affect`
  - eye expression influenced by `stress`/`fear`
  - accessory marks from `will` and `tempo`
- Status overlays:
  - `thinking` pulse
  - folded fade
  - winner highlight

## 5. Data Inputs
- Same event stream as existing visualizer:
  - `/api/replay?game_id=...`
  - `/api/stream?game_id=...`
- Required events:
  - `hand_started`
  - `action_resolved`
  - `showdown`
  - `hand_ended`
  - `thinking`
  - `turn_summary`

## 6. Controls
- `Load Replay`
- `Live Stream`
- `Prev`, `Next`, `Play/Pause`
- Event slider cursor for deterministic step navigation

## 7. Rendering Constraints
- Desktop first, responsive fallback.
- No external asset dependency required (sprites generated in-browser).
- All rendering from event state; no hidden mutable server state.

## 8. Acceptance Criteria
- Visual seats update correctly step-by-step under replay cursor.
- Player cards render in each seat.
- Sprite appearance changes with key characteristics (`will`, `skill_affect`, `stress`, `fear`).
- Live mode updates in near real-time without page refresh.
