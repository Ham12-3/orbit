# Orbit dev commands.
# Recipes only use commands that behave the same in sh and cmd.exe, so this works
# from Git Bash, PowerShell or a Unix shell (GNU make falls back to cmd on Windows).

API := uv --directory backend run

.DEFAULT_GOAL := help
.PHONY: help install dev db-up db-down migrate migrate-test revision test lint fmt typecheck check

help:
	@echo make install      - install backend + frontend deps, create .env files
	@echo make dev          - Postgres + migrations, then API, web and Inngest Dev Server
	@echo make test         - run backend tests (starts Postgres, migrates test DB)
	@echo make check        - lint + typecheck + test
	@echo make lint / fmt / typecheck
	@echo make migrate      - alembic upgrade head on the dev DB
	@echo make revision m="message" - autogenerate a migration
	@echo make db-up / db-down

install:
	uv --directory backend sync
	pnpm install
	pnpm --dir frontend install
	uv run --no-project scripts/init_env.py

dev: db-up migrate
	pnpm run dev

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

migrate:
	$(API) alembic upgrade head

migrate-test:
	$(API) alembic -x db=test upgrade head

revision:
	$(API) alembic revision --autogenerate -m "$(m)"

test: db-up migrate-test
	$(API) pytest

lint:
	$(API) ruff check .
	$(API) ruff format --check .
	pnpm --dir frontend lint

fmt:
	$(API) ruff check --fix .
	$(API) ruff format .

typecheck:
	$(API) mypy
	pnpm --dir frontend typecheck

check: lint typecheck test
