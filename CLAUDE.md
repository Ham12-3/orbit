# Orbit

A platform where users create named AI bots. Each bot has its own persistent E2B sandbox, runs the
Claude Agent SDK inside it, connects to the user's apps, runs on schedules and events, remembers what
it learns, and asks for approval before risky actions. The full spec is in [SPEC.md](SPEC.md); build
phases are in section 10 of it.

**Status:** Phase 2 (dashboard, Supabase login, chat with session resume, live run timelines) built.
Verified live: a two-message chat where the bot remembered the first message, streamed over SSE.
Next: Phase 3 (memory and files).

## Run it

Prerequisites: Docker Desktop (running), uv, Node 20.9+, pnpm 10, GNU make, and for bot runs the
Microsoft Dev Tunnels CLI (`winget install Microsoft.devtunnel`, then `devtunnel user login`).

```bash
make install            # deps; creates/updates .env and generates DEV_API_TOKEN + RUN_TOKEN_SECRET
# then set ANTHROPIC_API_KEY and E2B_API_KEY in .env
make tunnel-setup       # once: creates the dev tunnel, writes DEVTUNNEL_ID + PUBLIC_BASE_URL to .env
# Supabase (project ref mndvtcxmxfnmsvbcnvgv): SUPABASE_URL in .env, NEXT_PUBLIC_SUPABASE_* in
# frontend/.env.local. Dashboard settings it needs are listed under "Supabase setup" below.
make sandbox-template   # once, and after changing sandbox-template/template.py
make dev                # Postgres + migrations, then API, web, Inngest Dev Server and the tunnel
make try-run p="Create workspace/hello.txt containing today's date"   # bot=<id> reuses a bot
```

| Service | URL |
| --- | --- |
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 (docs at /docs) |
| Health | http://localhost:8000/health, /health/ready (checks DB) |
| Inngest endpoint | http://localhost:8000/api/inngest |
| Inngest Dev Server UI | http://localhost:8288 |
| Public URL (sandboxes) | `PUBLIC_BASE_URL` -> :8000 via the dev tunnel (`*-8000.<region>.devtunnels.ms`) |
| Postgres | localhost:5432, user/pass/db `orbit` (tests use `orbit_test`) |

Dashboard API (Supabase access token as `Authorization: Bearer`; in development the
`DEV_API_TOKEN` also works and acts as `DEV_USER_ID`):
- `GET /api/me`; bots: `POST/GET /api/bots`, `GET /api/bots/{id}`, `GET /api/bots/by-slug/{slug}`,
  `GET|POST /api/bots/{id}/runs`
- chat: `GET|POST /api/bots/{id}/threads` (POST `{"message"}`), `GET /api/threads/{id}`,
  `POST /api/threads/{id}/messages {"content"}`
- runs: `GET /api/runs/{id}` (with events), `POST /api/runs/{id}/cancel`,
  `POST /api/runs/{id}/stream-ticket`, `GET /api/runs/{id}/stream?ticket=...[&after=N]` (SSE)

### Supabase setup (once per project)

- Auth -> URL Configuration: Site URL `http://localhost:3000`; Redirect URLs add
  `http://localhost:3000/**`.
- Auth -> Emails -> Magic Link template: the link must carry a token hash for server-side
  verification:
  `<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email&next=/bots">Sign in</a>`
- The built-in email sender only mails members of the Supabase organization, 2 emails/hour.
- Signing keys must be asymmetric (new projects are; ours is ES256). HS256 tokens are rejected.

Other targets: `make test`, `make test-e2b` (live, needs keys + template), `make try-run`,
`make tunnel-setup`, `make lint`, `make fmt`,
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
scripts/devtunnel.py      `setup` (make tunnel-setup) and `host` (part of make dev)
scripts/try_run.py        make try-run: start a run and print its timeline
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
    auth/supabase.py      verify Supabase access tokens against the project's JWKS
    auth/stream_tickets.py short-lived, run-scoped tickets for EventSource streams
    api/                  dashboard routes (me, bots, threads, runs, health); deps.py: auth + deps
    chat/                 bot replies for finished chat runs, thread titles (Haiku)
    background.py         spawn()/drain() for fire-and-forget tasks (usage writes, titles)
    internal/             runner callbacks: /internal/runs/{id}/events and /complete
    llm_proxy/            /llm/v1/messages (+count_tokens): auth, budget, forward, meter, pricing
    runs/service.py       RunServices: enqueue, claim, start, check, finalize, cancel, sweeper
    runs/timeline.py      writing run_events
    runs/stream.py        the SSE generator (polls run_events ~1s, Last-Event-ID resume)
    sandboxes/            provider protocol, E2B implementation, in-sandbox layout + CLAUDE.md
    workflows/            Inngest client, execute-run workflow, sweeper cron, ping
  tests/                  fakes.py has FakeSandboxProvider + RecordingEvents
sandbox-template/         E2B template (template.py, build.py) and runner.py (runs in the sandbox)
frontend/                 Next.js 16 App Router, TS strict, Tailwind v4, shadcn/ui (Base UI)
  proxy.ts                Supabase session refresh + redirect to /login (Next 16's middleware)
  app/login, app/auth/confirm   magic-link sign-in (verifyOtp with token_hash)
  app/(app)/              signed-in pages: /bots, /bots/new, /bots/[slug], /runs/[id]
  components/             app-header, bots/*, runs/*, run-timeline, markdown, status-badge, ui/*
  lib/                    api.ts (fetch + bearer), queries.ts (TanStack Query), use-run-stream.ts,
                          supabase/{client,server,proxy}.ts, types.ts (mirror backend schemas)
```

Section 8 packages not yet created (`tool_gateway/`, `memory/`, `notifications/`) arrive with the
phase that first puts code in them.

Frontend rules: data comes from the API via TanStack Query hooks in `lib/queries.ts`; types in
`lib/types.ts` mirror the backend schemas. Under Cache Components, client components that read
`useParams`/`useSearchParams`/`usePathname` sit inside `<Suspense>` (pages wrap their client
view; the header wraps its active-link). shadcn here is Base UI: no `asChild`; style a `Link` with
`buttonVariants()`, Select needs `items` for labels.

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
  Aug 2026). `python:3.12` + git, curl, ripgrep, procps, bubblewrap; venv in `/opt/orbit`,
  root-owned. No Node: the Agent SDK wheel bundles the Claude Code binary (and its own ripgrep).
  2 vCPU, 2 GiB. A sandbox keeps the template it was created from: template changes only reach
  bots whose sandbox is created after the rebuild. `runner.py` is different: the backend writes
  the repo's current copy to `/opt/orbit/runner.py` as root at every run start, so runner fixes
  reach existing bots immediately.
- **Runner** (`sandbox-template/runner.py`): one `query()` with `setting_sources=["project"]`
  (loads `bot/CLAUDE.md`), `system_prompt` = claude_code preset, `strict_mcp_config`, cwd
  `/home/user/bot`, runs as non-root `user`. Env: `ANTHROPIC_BASE_URL={public}/llm`,
  `ANTHROPIC_AUTH_TOKEN=<run token>`, `ANTHROPIC_DEFAULT_HAIKU_MODEL` pinned (the CLI's background
  model), non-essential traffic and auto-memory off, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` (keeps
  the token out of the agent's shell; needs bubblewrap, and Claude Code refuses to start without
  it). The scrub also forces permission mode back to "default", so tools are pre-approved with
  `allowed_tools` (Bash, Read, Write, Edit, Glob, Grep, NotebookEdit, WebFetch, WebSearch, Task,
  ToolSearch, Skill) under `permission_mode="dontAsk"`; interactive-session tools (Cron*,
  ScheduleWakeup, Monitor, worktrees, SendMessage, ...) are in `disallowed_tools`. It deletes
  `bot/.claude/settings*.json` first (they could override the base URL), drops `ORBIT_*` from its
  own env, logs Claude Code's stderr and attaches its tail to crash reports. Events go through a
  background queue so slow HTTP never stalls the agent.
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
- **Dashboard auth = Supabase access tokens**, verified locally against the project's JWKS
  (ES256/RS256 only; issuer, `aud=authenticated`, `role=authenticated`, expiry checked; keys cached
  10 min, refetched on an unknown key id at most every 30 s). `DEV_API_TOKEN` works only when
  `ORBIT_ENV=development` and maps to `DEV_USER_ID` (for scripts like `make try-run`).
- **Login:** magic link via `signInWithOtp`; the email template links to `/auth/confirm` with a
  `token_hash`, which `verifyOtp` exchanges server-side (the default link puts the session in the
  URL fragment, which the server never sees). `proxy.ts` refreshes the session with `getClaims()`
  and redirects signed-out visitors. Sign-out uses `scope: "local"`.
- **Chat:** a message creates a `chat` run linked to its thread. The thread's `agent_session_id` is
  read at run start (so a queued follow-up resumes the latest session) and passed to the runner
  as `ORBIT_RESUME_SESSION_ID`. `chat/replies.ensure_bot_reply` writes the bot message from every
  ending (finalize, or cancelling a queued run): summary, or a short failure note. Titles: plain
  fallback immediately, then `claude-haiku-5-5` (thinking off) in the background; not metered.
- **Live runs over SSE:** EventSource cannot send headers, so the page gets a 5-minute,
  run-scoped stream ticket (HS256, audience `orbit-stream`, never accepted as a run token) and
  opens `/stream?ticket=`. The server polls `run_events` about once a second with a fresh session,
  sends `run_event` (with ids), `run` on any change, and `end`; FastAPI adds 15 s keep-alives.
  Tickets are redacted from the access log. The client re-tickets with `after=<last id>` when a
  stream is closed for good.
- **Tunnel = Microsoft Dev Tunnels**, not ngrok or Cloudflare. ngrok's free plan now requires agent
  3.28+ and Windows Defender quarantined the new ngrok download; Cloudflare Quick Tunnels do not
  support SSE (their docs) and named ones need a domain. A persistent dev tunnel keeps its URL
  across restarts, allows anonymous access, passes our `Authorization` header through (it uses
  `X-Tunnel-Authorization` for its own), and streamed a 3-minute SSE test unbuffered from inside an
  E2B sandbox. Created with `--request-timeout 0`. It is a preview service "for adhoc testing and
  development, not for production"; production gets a real URL in Phase 8. The tunnel's
  "inspect" URL requires the owner's login.
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
- If a bot's sandbox is replaced, its threads' Agent SDK sessions are gone and resuming fails; the
  run errors out. Phase 3/8: detect and start a fresh session.
- Thread titles call the Anthropic API outside any bot budget (tiny, Haiku).
- The Inngest Dev Server loses in-flight runs on restart; the sweeper cleans up within ~10 minutes
  after the run's deadline. Inngest Cloud in production does not have this problem.
- The dev tunnel needs the `devtunnel user login` token, valid "several days"; re-run the login
  if `make dev` shows the tunnel failing. The tunnel expires after 30 days without use, and is
  limited to 5 GB/month. Composio webhooks (Phase 5) can use the same stable URL.
- Bots created before a template rebuild keep their old sandbox. There is no "recreate sandbox"
  action yet (Phase 8 candidate); for now create a new bot.

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
- devtunnel CLI 1.0.2115: `create -a --expiration 30d --request-timeout 0 --json`, `port create
  <id> -p 8000 --protocol http`, `host <id>` (prints the URL; `show --json` does not).
- Claude Code (bundled with the SDK) 2.1.316.
- @supabase/ssr 0.12.7, @supabase/supabase-js 2.118, @tanstack/react-query 5.105, react-markdown 10,
  anthropic (Python) 2.4.0, PyJWT 2.15 with `crypto` extra (ES256 needs `cryptography`).
- FastAPI SSE is native since 0.135: `from fastapi.sse import EventSourceResponse, ServerSentEvent`,
  route `response_class=EventSourceResponse`, async generator body, 15 s keep-alive pings.
- inngest-cli 1.49.0, FastAPI 0.162, SQLAlchemy 2.1
  (`postgresql.distinct_on` replaces `.distinct(col)`), Alembic 1.20, pydantic-settings 2.16, PyJWT
  2.15, pytest 9, pytest-asyncio 1.4, Next.js 16.4, React 19.3, Tailwind 4.3, shadcn CLI 4.23.
