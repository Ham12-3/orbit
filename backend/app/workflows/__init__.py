"""Inngest client and durable functions, served from the FastAPI app."""

import inngest
import inngest.fast_api
from fastapi import FastAPI

from app.config import Settings
from app.workflows.client import create_inngest_client
from app.workflows.ping import build_ping


def build_functions(client: inngest.Inngest) -> list[inngest.Function[object]]:
    return [build_ping(client)]


def mount_inngest(app: FastAPI, settings: Settings) -> inngest.Inngest:
    """Serve all Inngest functions at /api/inngest and keep the client on app.state."""
    client = create_inngest_client(settings)
    inngest.fast_api.serve(app, client, build_functions(client))
    app.state.inngest = client
    return client
