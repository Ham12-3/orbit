# Orbit

A platform where users create named AI bots. Each bot has its own persistent E2B sandbox, runs the
Claude Agent SDK inside it, connects to the user's apps, runs on schedules and events, remembers what
it learns, and asks for approval before risky actions. The full spec is in [SPEC.md](SPEC.md); build
phases are in section 10 of it.

**Status:** Phase 0 (scaffold) done. Next: Phase 1 (one bot, one run, end to end).

## Run it

Prerequisites: Docker Desktop (running), uv, Node 20.9+, pnpm 10, GNU make.

```bash
make install   # uv sync, pnpm install (root + frontend), create .env and frontend/.env.local
make dev       # Postgres + migrations, then API, web and Inngest Dev Server together
```

| Service | URL |
| --- | --- |
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 (docs at /docs) |
| Health | http://localhost:8000/health, /health/ready (checks DB) |
| Inngest endpoint | http://localhost:8000/api/inngest |
| Inngest Dev Server UI | http://localhost:8288 |
| Postgres | localhost:5432, user/pass/db `orbit` (tests use `orbit_test`) |

Other targets: `make test`, `make lint`, `make fmt`, `make typecheck`, `make check` (all three),
`make migrate`, `make revision m="add bots"`, `make db-up`, `make db-down`. Run `make` to list them.

The Makefile must work from PowerShell, cmd and Git Bash: GNU make on Windows falls back to cmd.exe
when `sh` is not on PATH. Keep recipes to plain commands (no `cd`, `cp`, `rm`, env-var prefixes, shell
conditionals). Use `uv --directory backend` / `pnpm --dir frontend`, and Python scripts in `scripts/`
for anything else.

## Repo layout

```
SPEC.md, CLAUDE.md, README.md
Makefile                  entry point for every dev command
package.json              dev orchestration only: concurrently + inngest-cli (pinned)
docker-compose.yml        Postgres 16; infra/postgres/init creates orbit_test
scripts/init_env.py       copies .env examples without overwriting
backend/                  FastAPI control plane (uv, Python 3.12)
  pyproject.toml          deps + ruff, mypy, pytest, alembic config
  alembic/                migrations; env.py takes URL from Settings, metadata from app.models
  app/
    main.py               create_app(settings) factory
    dev.py                dev server entry point (run by watchfiles)
    config.py             Settings (pydantic-settings), reads repo-root .env
    logging_config.py     log format, httpx level, access-log filter
    db.py                 Database: async engine + sessionmaker, ping, dispose
    models/               SQLAlchemy models; base.py has Base + UUID/timestamp mixins
    schemas/              Pydantic request/response models
    api/                  dashboard routes; deps.py has shared dependencies
    workflows/            Inngest client + functions, mounted at /api/inngest
  tests/
frontend/                 Next.js 16 App Router, TS strict, Tailwind v4, shadcn/ui
  app/  components/  lib/
```

Section 8 packages (`auth/`, `llm_proxy/`, `tool_gateway/`, `sandboxes/`, `memory/`, `internal/`,
`notifications/`, `sandbox-template/`) are created in the phase that first puts code in them.

## Coding rules

- Read the current docs before using a library (links in SPEC.md section 12). If they disagree with
  the spec, follow the docs and tell the user what changed.
- Python: type hints everywhere, mypy strict, Pydantic v2, ruff (config in pyproject). No relative
  imports. Small modules.
- TypeScript: strict + `noUncheckedIndexedAccess`. Frontend lint with ESLint (next config).
- Every external call has a timeout and error handling (DB connect/command timeouts are in Settings).
- No secrets in code or git. New settings go in `app/config.py` and `.env.example` together.
- Every query that touches user data filters by the current user (from Phase 2).
- Never log run tokens, OAuth tokens or full email bodies at info level.
- Tests: `httpx.ASGITransport` against `create_app(settings)`. The `settings` fixture ignores the
  developer's `.env` and points at `orbit_test`. No silent skips: DB tests fail if Postgres is down.
- End of each phase: `make check` passes, update this file, commit, give manual test steps, stop.
- Line endings are LF (`.gitattributes`); sandbox code runs on Linux.

## Key decisions

- **App factory, no import-time side effects.** `create_app(settings)` builds everything; tests pass
  their own Settings. The `Database` object lives on `app.state.db` and is created eagerly (no I/O),
  so `ASGITransport` tests work without lifespan.
- **Inngest mode is explicit.** `is_production = not settings.inngest_dev`, so a stray `INNGEST_DEV`
  in the shell can't flip modes. Production needs `INNGEST_SIGNING_KEY` and `INNGEST_EVENT_KEY`.
  Functions are built by factories (`build_ping(client)`) rather than decorated at import time.
- **Alembic URL comes from Settings**, not alembic.ini. `alembic -x db=test upgrade head` targets the
  test DB. Alembic config lives in `[tool.alembic]` in pyproject; alembic.ini only holds logging.
  New revisions are auto-formatted with ruff. Constraint naming convention is set on `Base.metadata`.
- **Health:** `/health` is liveness (no deps). `/health/ready` pings the DB with a 2s timeout and
  returns 503 when it fails.
- **Frontend:** Next.js 16 defaults kept, including `cacheComponents` and `partialPrefetching`.
  Uncached server fetches must sit inside `<Suspense>`. Next 16 ships its docs in
  `frontend/node_modules/next/dist/docs/` (see frontend/AGENTS.md); read them before writing Next code.
- **shadcn/ui** uses its current default preset `base-nova`, built on Base UI (`@base-ui/react`), not
  Radix. Class merging comes from the `cn` package (shadcn's replacement for clsx + tailwind-merge).
  Dark mode is `next-themes` with the `class` attribute.
- **Dev processes** run under `concurrently` from the root package.json. `inngest-cli` is pinned and
  its postinstall is allowlisted via `pnpm.onlyBuiltDependencies`.
- **API hot reload uses `watchfiles app.dev.serve app`, not `uvicorn --reload`.** On Windows,
  uvicorn's reloader stops its worker with `CTRL_C_EVENT`, which never arrives under
  `concurrently`, so the reload hangs and the old code keeps serving. watchfiles terminates the
  process directly. Entry point: `app/dev.py`.
- **Logging** (`app/logging_config.py`): `httpx` is held at WARNING because it logs full request
  URLs at INFO (later these carry tokens). The Inngest Dev Server's 5-second sync polls
  (`PUT /api/inngest`) are filtered out of the uvicorn access log.

## Open issues for later phases

- **Per-bot run serialisation (Phase 1/5).** Inngest concurrency limits count *executing steps*, not
  runs; `wait_for_event` does not hold a slot. So `Concurrency(limit=1, key="event.data.bot_id")`
  will not give one run per bot with the decision-D workflow. Options: Inngest Singleton (check
  whether it queues or only skips/cancels) or a DB-backed per-bot queue. Decide in Phase 1 planning.
- **Public URL for sandboxes (Phase 1+).** E2B sandboxes cannot reach localhost. The runner
  callbacks, LLM proxy and MCP gateway need a public HTTPS URL (tunnel such as cloudflared or
  ngrok); Composio webhooks need a stable one in Phase 5.

## Library notes (verified 2026-11-02)

- inngest (Python) 0.5.19: `inngest.Inngest(app_id=..., is_production=..., signing_key=...,
  event_key=..., logger=...)`; `inngest.fast_api.serve(app, client, functions)` serves
  GET/POST/PUT at `/api/inngest`. Handlers are `async def fn(ctx: inngest.Context)`, steps via
  `ctx.step`. `create_function` takes `concurrency=[...]`, `singleton=...`, `timeouts=...`.
  GET on the endpoint returns `{"function_count", "mode", ...}`. It emits a Pydantic deprecation
  warning from its own code (filtered in pytest config).
- inngest-cli 1.49.0: `inngest-cli dev --no-discovery -u http://localhost:8000/api/inngest`, UI on 8288.
- FastAPI 0.162, Starlette 1.10, SQLAlchemy 2.1, Alembic 1.20 (`pyproject_async` template),
  pydantic-settings 2.16 (`NoDecode` for comma-separated list env vars), pytest 9, pytest-asyncio 1.4.
- Next.js 16.4, React 19.3, Tailwind 4.3, shadcn CLI 4.23.
