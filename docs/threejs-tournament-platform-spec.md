# 3D Tournament Platform Spec

Version: 0.1
Status: Design Draft (Not Implemented)

## 1. Purpose
Define the next-phase product surface: a 3D tournament viewer/control plane with multi-table simulation, avatar identity, and secure user-managed model endpoints.

## 2. Product Goals
1. Present active simulations as a readable, game-like 3D world.
2. Preserve current simulator rules and event contracts.
3. Support many concurrent games and tournament advancement.
4. Keep provider credentials private, encrypted, and tenant-scoped.

## 3. Primary User Flows
1. User signs in, opens `Tournament Arena`.
2. User creates a tournament with:
- seat format (`6-max` or `8-max`)
- entrant list (models and optional human seats later)
- stakes profile
3. User optionally registers OpenAI-compatible endpoint(s) and keys.
4. System starts bracket/round-robin progression.
5. Arena view shows multiple active tables with live animation.
6. Winners advance to higher-stakes tables in a pyramid topology.

## 4. 3D Client Experience
## 4.1 Stack
- Preferred: `Three.js` + `@react-three/fiber` + `@react-three/drei`.
- Fallback: Babylon.js if Three.js integration constraints appear.

## 4.2 Scene Layout
- One arena scene containing N tables.
- Table type supports `6` and `8` seats only.
- Table geometry height maps to current stake tier:
  - low stakes near floor
  - mid stakes elevated
  - high stakes highest platforms
- This creates a visual pyramid progression.

## 4.3 Table Entity
- `table_id`, `game_id`, `seat_count`, `stake_level`, `pot`, `phase`, `status`.
- Chairs are model-agnostic; any model can occupy any seat.
- Community board area reserved for future variants, even if current rules use private hands only.

## 4.4 Avatar System
- Each AI player chooses an avatar profile before first hand:
  - base body sprite/mesh
  - color palette
  - accessory set
  - emotion-expression style
- Selection source:
  - deterministic from seed + model_id by default
  - optional LLM choice from allowed catalog
- No free-form generated assets at runtime in v1.

## 4.5 Emotional Visualization
- Procedural face expression blend driven by emotion vector:
  - `fear`, `anger`, `shame`, `confidence`, `tilt`
- HUD indicators:
  - compact icon + bar per emotion
  - optional pulse when affect event lands
- "Thinking" state marker shown near active seat.

## 4.6 Multi-Table Navigation
- Global camera modes:
  - `overview` (all active tables)
  - `follow_table(table_id)`
  - `follow_player(player_id)` across advancements
- Table cards in world-space show:
  - blind/ante, pot, active players, elapsed hand time.

## 5. Tournament Engine Additions
## 5.1 Formats
- `single_elimination` (first implementation target)
- future: `swiss`, `round_robin`.

## 5.2 Advancement
- At round end, winner set promoted to next bracket node/table.
- Stakes increase by tier policy (e.g., x1.0, x1.5, x2.0).
- Seat fill policy:
  - preserve model identity
  - re-seat randomly within destination table.

## 5.3 Table Capacity Rules
- Tournament configured globally as 6-max or 8-max.
- Mixed capacities in one tournament are not supported in v1.

## 6. Backend Services
## 6.1 New Services
1. `Tournament Service`
- bracket generation, advancement, table lifecycle.
2. `Arena Projection Service`
- materialized view of world/table/player transforms for 3D clients.
3. `Credential Vault Service`
- encrypted provider credentials with rotation metadata.

## 6.2 Existing Service Reuse
- Simulator workers remain authoritative for hand resolution.
- Realtime gateway continues SSE/WebSocket event distribution.

## 7. Auth and Endpoint Management
## 7.1 Authentication
- User auth required for tournament creation and provider configuration.
- Recommended baseline:
  - OIDC (Auth0/Clerk/Keycloak) or self-hosted JWT auth.

## 7.2 Provider Endpoint Registration
- User can register OpenAI-compatible endpoint:
  - `base_url`
  - `api_key`
  - optional org/project headers
  - model allow-list
- Endpoint tied to owning user/org tenant.

## 7.3 Encryption Requirements
- API keys encrypted at rest with envelope encryption:
  - DEK per credential record
  - KEK managed by KMS or local master key for dev
- Secrets never sent back to frontend after create/update.
- Redacted logs only (`****last4`).

## 8. Data Contracts (New)
1. `avatar_selected`
- emitted when seat avatar profile finalized.
2. `table_spawned`
- new active table in arena projection.
3. `table_promoted`
- table moved to higher stake tier/height.
4. `player_advanced`
- entrant moved to destination table/seat.
5. `credential_registered`
- audit-only, no secret payload.

## 9. API Surface (Planned)
1. `POST /api/auth/session` (if not delegated fully to external IdP)
2. `POST /api/endpoints`
3. `GET /api/endpoints`
4. `POST /api/tournaments`
5. `GET /api/tournaments/:id`
6. `GET /api/arena/:tournament_id` (snapshot)
7. `GET /api/arena/stream?tournament_id=...` (live updates)

## 10. Non-Goals (v1)
- User-uploaded arbitrary 3D assets.
- Real-money payment rails.
- Cross-tournament persistent character progression.
- Fully hidden-information anti-cheat posture for competitive production.

## 11. Acceptance Criteria
1. Arena renders 20+ concurrent tables at >=30 FPS on mid-tier hardware.
2. Table height strictly monotonic with stake level.
3. Advancement events deterministically match tournament bracket state.
4. Endpoint secrets remain unreadable from DB dumps without KEK.
5. Tenant A cannot read or use Tenant B endpoint credentials.

