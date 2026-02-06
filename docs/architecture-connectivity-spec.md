# System Architecture Connectivity Spec

Version: 0.3
Status: Draft

## 1. Purpose
Define how engine, agent runtime, provider routing, data stores, and web visualizer connect for live simulation and replay.

## 2. High-Level Components
1. `Game Engine`
- deterministic rules, turn/phase orchestration, action validation, resolution.

2. `Agent Runtime`
- executes LLM seats: perception, appraisal, deliberation, dialogue, action selection, reflection.

3. `LLM Router`
- provider abstraction (LiteLLM), model fallback, timeouts/retries, usage accounting.

4. `State Store`
- canonical game state snapshots and derived projections.

5. `Event Log`
- append-only event stream for replay/debug/audit.

6. `Realtime Gateway`
- publishes events/snapshots to web clients.

7. `Web Visualizer`
- subscribes to live stream and replay API.

8. `Orchestrator`
- launches games, tournaments, seeds, and simulation workers.
9. `Tournament Service` (planned)
- bracket generation, table assignments, advancement.
10. `Arena Projection Service` (planned)
- computes and serves 3D world/table/player projection state.
11. `Credential Vault` (planned)
- encrypted storage for user-scoped provider credentials.

## 3. Runtime Topology
- Current implemented topology:
  - single Python process: engine + agent runtime + provider client + visualizer HTTP server.
  - append-only JSONL event logs under `runs/`.
  - SSE stream endpoint for live web updates.
- Scale-out target:
  - simulation workers separate from API/realtime tier.
  - shared postgres + message broker.

## 4. Control Flow (Live Game)
1. Orchestrator creates game with config + seed.
2. Engine emits `game_started` and initial snapshot.
3. For each phase:
- engine requests plans/dialogue from Agent Runtime.
- Agent Runtime calls LLM Router.
- Router calls selected provider endpoint.
- validated actions returned to engine.
- engine resolves outcomes and updates state.
- engine writes events and snapshot deltas.
- Realtime Gateway pushes updates to clients.
4. On terminal condition, engine emits `game_ended`.

## 5. Data Flow Contracts
- Engine is source of truth for legality and outcome.
- Agent Runtime is advisory; cannot mutate state directly.
- Visualizer is read-only consumer; never calls provider endpoints.
- Event log is immutable; corrections are compensating events.

## 6. Connectivity Interfaces
## 6.1 Engine <-> Agent Runtime
- synchronous boundary per decision window:
  - `request_turn_plan`
  - `request_dialogue`
  - `request_reaction`
  - `request_reflection`
- strict JSON schemas and timeout budget.

## 6.2 Agent Runtime <-> LLM Router
- provider-agnostic inference request:
  - model id
  - schema
  - prompt package
  - generation params
  - budget + deadline

## 6.3 Realtime Gateway <-> Visualizer
- current: SSE stream (`/api/stream`) + replay fetch (`/api/replay`).
- visualizers:
  - dashboard view: `/`
  - pixel top-view table: `/table`
- replay controls are client-side with deterministic event cursor rebuild.

## 6.4 API Surface
- implemented:
  - `GET /api/games`
  - `GET /api/replay?game_id=...`
  - `GET /api/stream?game_id=...` (SSE)
- planned:
  - `POST /games`
  - `POST /tournaments`

## 7. Failure and Fallback Strategy
- provider timeout:
  - retry with same model once
  - fallback model chain
  - if still fails, safe fallback action (`pass`/minimal-risk legal action)
- malformed output:
  - schema re-prompt once
  - then fallback action
- realtime disconnect:
  - client reconnect with resume token

## 8. Security and Isolation
- role-based access for spectator/researcher/admin.
- API keys only on server side.
- prompt and private state access gated by role.
- audit log for privileged data access.

## 9. Deployment Profiles
1. Local research
- docker-compose optional, local Ollama/LM Studio endpoints.

2. Hosted simulation
- managed DB, stateless API/realtime pods, worker pool.

3. Hosted tournament arena (planned)
- adds tournament service, arena projection service, auth provider, and secret management (KMS-backed where available).

## 10. Observability
- structured logs with `game_id`, `turn`, `phase`, `player_id`, `event_id`.
- metrics:
  - provider latency/cost
  - invalid action rate
  - reconnect frequency
  - event lag (engine emit to client receive)
- tracing across engine -> runtime -> router -> provider.

## 11. Acceptance Criteria
- Same seed + same model outputs yields deterministic replay.
- Visualizer reconnect restores continuity without state corruption.
- Provider outage degrades gracefully without crashing simulation.
- Role boundaries prevent hidden/private leakage to spectator clients.
- Per-player model assignment works with graceful fallback when assigned model is unavailable.

## 12. Next-Phase Link
- 3D arena and secure multi-table tournament requirements are specified in `docs/threejs-tournament-platform-spec.md`.
