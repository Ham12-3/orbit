# Orbit dev commands.
# Recipes only use commands that behave the same in sh and cmd.exe, so this works
# from Git Bash, PowerShell or a Unix shell (GNU make falls back to cmd on Windows).

API := uv --directory backend run

.DEFAULT_GOAL := help
.PHONY: help install dev db-up db-down migrate migrate-test revision test test-e2b lint fmt typecheck check sandbox-template

help:
	@echo make install      - install deps, create/update .env files and generated secrets
	@echo make dev          - Postgres + migrations, then API, web, Inngest Dev Server, ngrok
	@echo make sandbox-template - build the bot sandbox template on E2B
	@echo make test         - run backend tests (starts Postgres, migrates test DB)
	@echo make test-e2b     - live check against E2B: no real key inside a sandbox
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

test-e2b:
	$(API) pytest -m e2b

sandbox-template:
	$(API) python ../sandbox-template/build.py

lint:
	$(API) ruff check . ../sandbox-template ../scripts
	$(API) ruff format --check . ../sandbox-template ../scripts
	pnpm --dir frontend lint

fmt:
	$(API) ruff check --fix . ../sandbox-template ../scripts
	$(API) ruff format . ../sandbox-template ../scripts

typecheck:
	$(API) mypy
	pnpm --dir frontend typecheck

check: lint typecheck test
