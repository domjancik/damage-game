# Damage Game Simulator

Initial implementation scaffold for a Damage-inspired card simulation with LLM-controlled players and emotion-aware attacks.

## Quick start

```powershell
$env:DAMAGE_BASE_URL="http://192.168.1.103:1234/v1"
$env:DAMAGE_MODEL="qwen2.5-14b-instruct-mlx"
$env:DAMAGE_FALLBACK_MODELS="mistral-small-3.2-24b-instruct-2506-mlx"
uv run --python 3.11 -m damage_game.cli --turns 2 --players 4
```

Optional API key (if endpoint requires it):

```powershell
$env:DAMAGE_API_KEY="your_key"
```

Probe endpoint models:

```powershell
uv run --python 3.11 -m damage_game.cli --probe --base-url http://192.168.1.103:1234/v1
```

Run logs are written under `runs/` and include per-call token usage plus required context capacity estimates.

Poker-like stakes tuning:

```powershell
uv run --python 3.11 -m damage_game.cli --players 4 --turns 5 --seed 42 --ante 10 --min-raise 10 --starting-bankroll 200
```

Per-player model assignment:

```powershell
uv run --python 3.11 -m damage_game.cli --players 4 --player-models "P1=mistral-small-3.2-24b-instruct-2506-mlx,P2=qwen2.5-14b-instruct-mlx"
```

Life risk rule:
- `fold` avoids life loss for that hand (chips committed stay in pot).
- Players who stay to showdown and lose lose 1 Life.
- Uneven all-ins use side-pot payout splitting.

Affect phase:
- Before betting, each player can choose bounded affect tactics (`attack`, `assist`, `guard`, `self_regulate`, `none`) using `will/skill/focus/stress`.
- `self_regulate` spends focus to reduce stress and negative affect with hard caps.

## Replay logs

```powershell
uv run --python 3.11 -m damage_game.replay_cli --list
uv run --python 3.11 -m damage_game.replay_cli --game-id game_20260206T093854Z --speed 2
```

## Live visualizer

```powershell
uv run --python 3.11 -m damage_game.visualizer_cli --host 127.0.0.1 --port 8787 --log-dir runs
```

Then open `http://127.0.0.1:8787`, select a game, and choose `Load Replay` or `Live Stream`.

## Documentation

- `docs/implementation-status.md`: current feature coverage, event coverage, known gaps, and next docs.
- `docs/damage-sim-spec.md`: game design and implemented rules baseline.
- `docs/schema-spec.md`: event/action/player schema reference.
- `docs/architecture-connectivity-spec.md`: runtime architecture and API/stream connectivity.
- `docs/realtime-visualizer-spec.md`: dashboard visualizer requirements.
- `docs/pixel-topdown-visualizer-spec.md`: pixel top-view table visualizer design.
- `docs/threejs-tournament-platform-spec.md`: planned 3D arena, tournament progression, avatar system, and secure endpoint onboarding.
