# Orbit

AI bots that do real work on their own: each bot gets its own persistent cloud computer, connects to
your apps, runs on schedules and events, remembers what it learns, and asks before risky actions.

See [SPEC.md](SPEC.md) for the product spec and [CLAUDE.md](CLAUDE.md) for the engineering guide.

## Quickstart

Prerequisites: Docker Desktop (running), [uv](https://docs.astral.sh/uv/), Node 20.9+, pnpm 10,
GNU make, and the Microsoft Dev Tunnels CLI (`winget install Microsoft.devtunnel`, then
`devtunnel user login`) so bot sandboxes can reach your machine.

```bash
make install
```

Then fill in `ANTHROPIC_API_KEY`, `E2B_API_KEY` and `SUPABASE_URL` in `.env`, the
`NEXT_PUBLIC_SUPABASE_*` values in `frontend/.env.local`, apply the Supabase dashboard settings
listed in CLAUDE.md ("Supabase setup"), and:

```bash
make tunnel-setup
make sandbox-template
make dev
```

Try a bot run (in another terminal):

```bash
make try-run p="Create workspace/hello.txt containing today's date"
```

Then open:

- Web: http://localhost:3000 (sign in with a magic link)
- API health: http://localhost:8000/health
- Inngest Dev Server: http://localhost:8288

Run `make check` for lint, type checks and tests.
