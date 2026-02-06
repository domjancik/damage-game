# Realtime Web Visualizer Spec

Version: 0.1
Status: Draft

## 1. Purpose
Define a realtime web UI for observing live Damage simulation games, including tactical state, social-emotional dynamics, and model decisions, without exposing hidden private data to unauthorized viewers.

## 2. Product Goals
1. Live observability of game progression with sub-second updates for core state.
2. Clear separation of public state vs privileged/debug state.
3. Replayability: identical timeline reconstruction from event logs.
4. Operator controls for pause/resume/speed/seed-run selection.

## 3. Users and Views
- `Spectator`: sees public game state, public chat, resolved actions.
- `Researcher`: spectator view plus derived emotional analytics (no raw hidden prompts by default).
- `Developer/Admin`: full debug including per-agent internals and schema validation traces.

## 4. Realtime Requirements
- Update transport: WebSocket (primary), SSE fallback.
- Tick model:
  - `state_delta` events at 4-10 Hz target during active windows.
  - `phase_change` events on phase transitions.
  - `action_resolved` events immediately after deterministic resolution.
- Latency SLO:
  - p95 server-to-client delivery under 400 ms on local/LAN.

## 5. UI Surface
## 5.1 Main Layout
- Left: turn/phase timeline and event feed.
- Center: table state panel (active cards, resolve/lives/tempo/exposure).
- Right: social-emotion panel (trust matrix, grievance, emotion vectors).
- Bottom: chat transcript with channel tags (`public`, `private`, `system`).

## 5.2 Core Panels
1. `Game Header`
- game id, seed, turn, phase, active player, mode (live/replay).

2. `Table State`
- public hands count, arena cards, discard stacks, counters.
- animations for card play, counter shifts, eliminations.

3. `Intent/Attack Inspector`
- resolved action payload:
  - kinetic intent
  - emotional intent
  - manipulation plan
  - expected behavior shift
  - actual tactical + affective outcomes

4. `Emotion Dashboard`
- per-player radar/line charts for fear/anger/shame/confidence/tilt.
- trust and grievance heatmaps.
- change markers per event.

5. `Model Trace (Privileged)`
- model id/provider, token usage, latency, retries, validation failures.
- redacted prompt/response excerpts gated by role.

## 6. Interaction Model
- Live controls:
  - pause/resume
  - playback speed (`0.25x`, `1x`, `2x`, `4x`)
  - auto-follow latest event
- Replay controls:
  - scrubber by event index/turn
  - jump to phase boundaries
  - diff two timepoints for state changes

## 7. Data and Event Contract
All messages are JSON with envelope:
- `type`
- `game_id`
- `turn`
- `phase`
- `event_id`
- `ts`
- `payload`

Minimum event types:
- `game_started`
- `phase_changed`
- `speech_posted`
- `action_submitted`
- `action_rejected`
- `action_resolved`
- `emotion_updated`
- `player_eliminated`
- `game_ended`

State sync:
- Full snapshot on connect.
- Delta stream thereafter.
- Snapshot hash every N events for drift detection.

## 8. Privacy and Redaction
- Public clients must never receive hidden hand contents or private commitments before reveal.
- Private messages are hidden unless viewer role permits.
- Admin redaction policy for prompts:
  - default redact chain-of-thought style text.
  - expose structured summaries and final JSON decisions.

## 9. Reliability
- Client reconnect with last `event_id` resume token.
- Server replays missed events from durable event log.
- Heartbeat every 10 seconds; stale connection timeout 30 seconds.

## 10. Accessibility and UX Constraints
- Desktop first, mobile-responsive fallback.
- Color + shape encoding for emotion deltas (avoid color-only encoding).
- Keyboard navigation for timeline and playback controls.

## 11. Tech Recommendation
- Frontend: React + TypeScript + Vite.
- Realtime: native WebSocket endpoint.
- Charts: lightweight timeseries/heatmap library.
- State: event-store driven client cache keyed by `event_id`.

## 12. Acceptance Criteria
- Spectator can follow live game state with no manual refresh.
- Replay of same event log reproduces identical UI timeline.
- Redaction constraints verified by role tests.
- Attack inspector always displays emotional manipulation metadata for valid attacks.
