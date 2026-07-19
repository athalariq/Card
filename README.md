# LarpCard

LarpCard is a modular Discord collectible card game built with Python 3.12,
discord.py, PostgreSQL, Redis, SQLAlchemy, Alembic, and Pillow.

This repository currently contains the first playable vertical slice:

- asynchronous application bootstrap and dependency wiring
- card, series, player, drop, slot, and ownership persistence models
- PostgreSQL-backed atomic claims using row locks
- Redis-backed distributed drop cooldowns
- weighted 2-4 card drops with expiring Discord claim buttons
- a 401 x 555 premium card renderer and responsive drop contact sheet
- an initial Alembic migration and focused unit tests

## Local setup

Create a virtual environment and install the package:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Set `LARPCARD_DISCORD_TOKEN` in `.env`, then start PostgreSQL and Redis:

```powershell
docker compose up -d postgres redis
$env:LARPCARD_DATABASE_URL = "postgresql+asyncpg://larpcard:larpcard@localhost:5432/larpcard"
$env:LARPCARD_REDIS_URL = "redis://localhost:6379/0"
alembic upgrade head
larpcard
```

The `.env.example` service URLs target the Compose network. To run the complete
containerized stack, copy it to `.env`, set the Discord token, and run:

```powershell
docker compose up --build
```

The one-shot `migrate` service applies Alembic revisions before the bot starts.

Run tests:

```powershell
python -m pytest
python -m ruff check .
python -m mypy src
```

PostgreSQL and Redis integration tests are enabled when
`LARPCARD_TEST_DATABASE_URL` and `LARPCARD_TEST_REDIS_URL` point to disposable
test services. They are skipped by default because the PostgreSQL test creates
and drops an isolated schema.

## Assets

Card definitions store artwork and optional frame paths relative to
`LARPCARD_ASSET_ROOT`. Put imported artwork under `assets/artwork/` and custom
frames under `assets/frames/`. The generated renderer still provides metallic
rarity frames when no custom frame is supplied.

Import card metadata from a validated JSON catalog after artwork is present:

```powershell
$env:LARPCARD_DATABASE_URL = "postgresql+asyncpg://larpcard:larpcard@localhost:5432/larpcard"
$env:LARPCARD_ASSET_ROOT = "$PWD/assets"
larpcard-import-catalog catalog.example.json
```

The importer updates matching `character + edition + variant` definitions,
creates missing series and characters, and deliberately preserves existing
print counters. Use `--allow-missing-assets` only for staged metadata imports.

## Architecture

Business rules live in feature packages and depend on typed protocols. Discord,
SQLAlchemy, Redis, and the local filesystem are adapters. This keeps drop and
claim behavior testable without external services and leaves room for future
dashboard, recognition, marketplace, and admin applications.
