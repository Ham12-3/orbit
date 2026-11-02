# Orbit

AI bots that do real work on their own: each bot gets its own persistent cloud computer, connects to
your apps, runs on schedules and events, remembers what it learns, and asks before risky actions.

See [SPEC.md](SPEC.md) for the product spec and [CLAUDE.md](CLAUDE.md) for the engineering guide.

## Quickstart

Prerequisites: Docker Desktop (running), [uv](https://docs.astral.sh/uv/), Node 20.9+, pnpm 10,
GNU make.

```bash
make install
make dev
```

Then open:

- Web: http://localhost:3000
- API health: http://localhost:8000/health
- Inngest Dev Server: http://localhost:8288

Run `make check` for lint, type checks and tests.
