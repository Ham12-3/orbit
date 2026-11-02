"""Inngest client and durable functions, served from the FastAPI app."""

from typing import Any

import inngest
import inngest.fast_api
from fastapi import FastAPI

from app.runs.service import RunServices
from app.workflows.ping import build_ping
from app.workflows.run import build_run_functions


def build_functions(client: inngest.Inngest, services: RunServices) -> list[inngest.Function[Any]]:
    return [build_ping(client), *build_run_functions(client, services)]


def mount_inngest(app: FastAPI, client: inngest.Inngest, services: RunServices) -> None:
    """Serve all Inngest functions at /api/inngest."""
    inngest.fast_api.serve(app, client, build_functions(client, services))
