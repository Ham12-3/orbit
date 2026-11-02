# Orbit

A platform where users create named AI bots. Each bot has its own persistent E2B sandbox, runs the
Claude Agent SDK inside it, connects to the user's apps, runs on schedules and events, remembers what
it learns, and asks for approval before risky actions. The full spec is in [SPEC.md](SPEC.md); build
phases are in section 10 of it.

**Status:** Phase 1 (one bot, one run, end to end; API only) built. Next: Phase 2 (dashboard, auth,
chat, live runs).

## Run it

Prerequisites: Docker Desktop (running), uv, Node 20.9+, pnpm 10, GNU make, ngrok (with an authtoken
and a static domain) for bot runs.

```bash
make install            # deps; creates/updates .env and generates DEV_API_TOKEN + RUN_TOKEN_SECRET
# then set ANTHROPIC_API_KEY, E2B_API_KEY and PUBLIC_BASE_URL=https://<static>.ngrok-free.app in .env
make sandbox-template   # once, and whenever sandbox-template/ changes
make dev                # Postgres + migrations, then API, web, Inngest Dev Server and the ngrok tunnel
```

| Service | URL |
| --- | --- |
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 (docs at /docs) |
| Health | http://localhost:8000/health, /health/ready (checks DB) |
| Inngest endpoint | http://localhost:8000/api/inngest |
| Inngest Dev Server UI | http://localhost:8288 |
| Public URL (sandboxes) | `PUBLIC_BASE_URL` -> :8000 via ngrok (inspector on :4040) |
| Postgres | localhost:5432, user/pass/db `orbit` (tests use `orbit_test`) |

Phase 1 API (send `Authorization: Bearer $DEV_API_TOKEN`): `POST /api/bots`, `GET /api/bots`,
`GET /api/bots/{id}`, `POST /api/bots/{id}/runs {"prompt"}`, `GET /api/runs/{id}` (with events),
`POST /api/runs/{id}/cancel`.

Other targets: `make test`, `make test-e2b` (live, needs keys + template), `make lint`, `make fmt`,
`make typecheck`, `make check` (lint + typecheck + test), `make migrate`, `make revision m="..."`,
`make db-up`, `make db-down`. Run `make` to list them.

The Makefile must work from PowerShell, cmd and Git Bash: GNU make on Windows falls back to cmd.exe
when `sh` is not on PATH. Keep recipes to plain commands (no `cd`, `cp`, `rm`, env-var prefixes, shell
conditionals). Use `uv --directory backend` / `pnpm --dir frontend`, and Python scripts in `scripts/`
for anything else.

## Repo layout

```
SPEC.md, CLAUDE.md, README.md
Makefile                  entry point for every dev command
package.json              dev orchestration only: concurrently + inngest-cli (pinned)
ruff.toml                 applies backend's ruff config to sandbox-template/ and scripts/
docker-compose.yml        Postgres 16; infra/postgres/init creates orbit_test
scripts/init_env.py       creates/updates .env from .env.example, generates secrets
scripts/tunnel.py         ngrok http 8000 --url $PUBLIC_BASE_URL (part of make dev)
backend/                  FastAPI control plane (uv, Python 3.12)
  pyproject.toml          deps + ruff, mypy, pytest, alembic config
  alembic/                migrations; env.py takes URL from Settings, metadata from app.models
  app/
    main.py               create_app(settings, sandboxes=, events=, llm_http=) factory
    dev.py                dev server entry point (run by watchfiles)
    config.py             Settings (pydantic-settings), reads repo-root .env
    events.py             Inngest event names + EventSender (fakeable)
    db.py                 Database: async engine + sessionmaker, ping, dispose
    models/               bots, runs, run_events, run_tokens, llm_usage; enums as checked VARCHARs
    schemas/              Pydantic request/response models
    auth/run_tokens.py    issue / verify / revoke run tokens (JWT + stored SHA-256)
    api/                  dashboard routes (bots, runs, health); deps.py: auth + shared deps
    internal/             runner callbacks: /internal/runs/{id}/events and /complete
    llm_proxy/            /llm/v1/messages (+count_tokens): auth, budget, forward, meter, pricing
    runs/service.py       RunServices: enqueue, claim, start, check, finalize, cancel, sweeper
    runs/timeline.py      writing run_events
    sandboxes/            provider protocol, E2B implementation, in-sandbox layout + CLAUDE.md
    workflows/            Inngest client, execute-run workflow, sweeper cron, ping
  tests/                  fakes.py has FakeSandboxProvider + RecordingEvents
sandbox-template/         E2B template (template.py, build.py) and runner.py (runs in the sandbox)
frontend/                 Next.js 16 App Router, TS strict, Tailwind v4, shadcn/ui
```

Section 8 packages not yet created (`tool_gateway/`, `memory/`, `notifications/`) arrive with the
phase that first puts code in them.

## Coding rules

- Read the current docs before using a library (links in SPEC.md section 12). If they disagree with
  the spec, follow the docs and tell the user what changed.
- Python: type hints everywhere, mypy strict, Pydantic v2, ruff. No relative imports. Small modules.
- TypeScript: strict + `noUncheckedIndexedAccess`. Frontend lint with ESLint (next config).
- Every external call has a timeout and error handling (DB, E2B, Inngest and upstream LLM timeouts
  are in Settings / the clients).
- No secrets in code or git. New settings go in `app/config.py` and `.env.example` together.
- Every query that touches user data filters by the current user (bots by `user_id`, runs via bot).
- Never log run tokens, OAuth tokens or full email bodies at info level. httpx stays at WARNING.
- Sandbox-facing code must never receive a real secret. `tests/test_run_lifecycle.py::
  test_real_secrets_never_reach_the_sandbox` enforces this; extend it when adding sandbox inputs.
- Run state changes are conditional UPDATEs (`RunServices._transition`), because cancels and runner
  callbacks race with the workflow. Never set `run.status` on a loaded object and commit.
- Workflow steps call `RunServices` methods that open their own session, are retry-safe, and return
  JSON values. Never return a run token from a step (step output is stored by Inngest).
- Tests: `httpx.ASGITransport` against `create_app(settings, ...fakes)`. The `app` fixture truncates
  tables. No silent skips: DB tests fail if Postgres is down. Live E2B tests are marked `e2b`.
- End of each phase: `make check` passes, update this file, commit, give manual test steps, stop.
- Line endings are LF (`.gitattributes`); sandbox code runs on Linux.

## Key decisions

- **One run per bot = a Postgres queue, not Inngest concurrency.** Inngest concurrency counts
  executing steps (a waiting run holds no slot); Singleton skips or cancels; Throttle limits starts.
  So: a trigger inserts a `queued` run and sends `orbit/run.requested`. `claim` locks the bot row
  and sets `bots.active_run_id`; a busy bot leaves the run queued. `finalize` releases the bot and
  dispatches the oldest queued run. A 1-minute sweeper cron re-dispatches stranded queued runs and
  finalizes runs whose workflow died (the Dev Server keeps state in memory, so restarts lose runs).
- **Run workflow** (`workflows/run.py`): claim -> start -> wait in 2-minute slices for
  `orbit/run.finished` (an event sent before a wait starts is not matched) with a `check` step after
  each slice (deadline -> `timed_out`, dead runner -> `failed`) -> finalize -> dispatch next.
  `ConfigurationError` becomes `NonRetriableError`; `on_failure` marks the run failed and finalizes.
  Cancel is ours, not Inngest's `cancel`, which would skip finalize.
- **Sandbox per bot (E2B).** Created on the first run with `lifecycle.on_timeout = pause` (the API
  default is kill, which would delete the bot's computer) and reused via `connect` (auto-resume).
  After each run: kill the runner tree, `pause(mode="filesystem")` (RAM is not needed; every run
  starts a fresh runner). If the sandbox is gone, a new one is created and the run timeline says so.
  Background commands need `timeout=0` or E2B kills them after 60s.
- **Template:** E2B's code-defined `Template()` builder (V1 Dockerfile builds were removed in
  Aug 2026). `python:3.12` + git, curl, ripgrep, procps; runner + venv in `/opt/orbit`, root-owned.
  No Node: the Agent SDK wheel bundles the Claude Code binary (and its own ripgrep). 2 vCPU, 2 GiB.
- **Runner** (`sandbox-template/runner.py`): one `query()` with `setting_sources=["project"]`
  (loads `bot/CLAUDE.md`), `system_prompt` = claude_code preset, `permission_mode=bypassPermissions`
  (the sandbox is the boundary; runs as non-root `user`), `strict_mcp_config`, cwd `/home/user/bot`.
  Env: `ANTHROPIC_BASE_URL={public}/llm`, `ANTHROPIC_AUTH_TOKEN=<run token>`,
  `ANTHROPIC_DEFAULT_HAIKU_MODEL` pinned (the CLI's background model), non-essential traffic and
  auto-memory off, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`. It deletes `bot/.claude/settings*.json`
  first (they could override the base URL) and drops `ORBIT_*` from its own env. Events go through
  a background queue so slow HTTP never stalls the agent.
- **Run tokens:** HS256 JWT (`sub`=run, `bot`, `aud=orbit-run`, exp = run timeout + 10 min); only
  the SHA-256 is stored; revoked on finalize and cancel. Accepted as Bearer or `x-api-key`.
  `RUN_TOKEN_SECRET` must be 32+ chars.
- **LLM proxy uses httpx, not the anthropic SDK** (spec said SDK): Claude Code's gateway protocol
  needs the body and `anthropic-*` headers forwarded byte for byte and SSE relayed unbuffered. It
  forwards an allow-list of headers, sets `x-api-key` and `accept-encoding: identity`, and parses
  usage from `message_start`/`message_delta` as bytes pass. Usage is written in a background task.
  Budget exhausted -> 403 `permission_error` (the CLI retries 429s).
- **Budgets and cost:** `llm_usage` has one row per proxied call (authoritative, unlike the SDK's
  estimate). Daily budget = input + cache writes + output since 00:00 UTC; cache reads are excluded
  (the agent re-reads its whole prefix every turn). Prices in `llm_proxy/pricing.py` from the
  official pricing page; its keys are the model allow-list.
- **Dashboard auth (Phase 1 only):** a static `DEV_API_TOKEN` bearer and one `DEV_USER_ID`. Needed
  because the tunnel makes the backend public. Phase 2 swaps `get_current_user` for Supabase JWTs.
- **run_events** use a bigint identity id (total order, future SSE cursor) and a nullable runner
  `seq` (unique per run, for idempotent retries). Server-written status events have no seq.
- **Bot identity:** `CLAUDE.md` is rendered from the bot's config and rewritten at every run start
  (`sandboxes/layout.py`), so it is always current. Phase 3 adds memory sync.
- **App factory, no import-time side effects.** Tests inject fakes for E2B, events and the upstream.
- **Inngest mode is explicit** (`is_production = not settings.inngest_dev`).
- **Alembic URL comes from Settings**; `alembic -x db=test upgrade head` targets the test DB.
- **API hot reload uses `watchfiles app.dev.serve app`, not `uvicorn --reload`** (uvicorn's Windows
  reloader hangs under `concurrently`).
- **Frontend:** Next.js 16 defaults (`cacheComponents`), shadcn `base-nova` (Base UI), `next-themes`.

## Known risks and open issues

- The agent's own shell can read the run token from its process tree (same Linux user). Accepted:
  short-lived, scoped to one run, revoked at the end, only buys budget-capped LLM calls and event
  writes for that run. Full fix (run the CLI as a second user) is a Phase 8 candidate.
- No rate limiting on public endpoints yet (spec section 7); planned for Phase 8.
- The Inngest Dev Server loses in-flight runs on restart; the sweeper cleans up within ~10 minutes
  after the run's deadline. Inngest Cloud in production does not have this problem.
- Composio webhooks (Phase 5) need the ngrok static domain to stay stable.

## Library notes (verified 2026-11-02)

- claude-agent-sdk 0.2.176: `query(prompt=, options=ClaudeAgentOptions(...))`; messages
  `AssistantMessage` (TextBlock / ThinkingBlock / ToolUseBlock), `UserMessage` (ToolResultBlock),
  `SystemMessage(subtype="init")`, `ResultMessage` (subtype, is_error, result, session_id,
  num_turns, errors, api_error_status). A failed single-shot query raises after yielding its result.
- e2b 2.62.0: `AsyncSandbox.create(template=, timeout=, metadata=, lifecycle=, api_key=,
  request_timeout=)`, `AsyncSandbox.connect(id, timeout=)` resumes, `AsyncSandbox.pause(id, mode=)`,
  `commands.run(cmd, background=True, timeout=0, envs=, cwd=)` -> handle (`.pid`, `.disconnect()`),
  `commands.list()`, `files.write/make_dir`. Template: `Template().from_python_image("3.12")
  .apt_install([...]).run_cmd([...], user="root").copy(src, dest, user=, mode=)`;
  `Template.build(template, name, cpu_count=, memory_mb=)`. Hobby: 1 h max continuous runtime.
- inngest (Python) 0.5.19: `create_function(fn_id=, trigger=, retries=, on_failure=)`;
  `ctx.step.run(id, fn, *args)`, `ctx.step.wait_for_event(id, event=, if_exp=, timeout=)` (None on
  timeout), `ctx.step.send_event(id, events)`, `TriggerCron(cron=)`, `NonRetriableError`.
- Pricing per MTok (input / 5m write / 1h write / cache read / output): Opus 5.5 4 / 5 / 8 / 0.20 / 20;
  Sonnet 5.5 2 / 2.50 / 4 / 0.10 / 10; Haiku 5.5 0.10 / 0.125 / 0.20 / 0.01 / 0.50, and 5x all rates
  when the prompt (incl. cache tokens) is over 100K.
- inngest-cli 1.49.0, ngrok 3.20 (`ngrok http 8000 --url <url>`), FastAPI 0.162, SQLAlchemy 2.1
  (`postgresql.distinct_on` replaces `.distinct(col)`), Alembic 1.20, pydantic-settings 2.16, PyJWT
  2.15, pytest 9, pytest-asyncio 1.4, Next.js 16.4, React 19.3, Tailwind 4.3, shadcn CLI 4.23.
