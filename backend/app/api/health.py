"""Liveness and readiness probes."""

import asyncio
import logging

from fastapi import APIRouter, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DatabaseDep
from app.schemas.health import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

READINESS_DB_TIMEOUT_S = 2.0


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness: the process is up. Checks no dependencies."""
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(db: DatabaseDep, response: Response) -> ReadinessResponse:
    """Readiness: the process can reach its database."""
    try:
        async with asyncio.timeout(READINESS_DB_TIMEOUT_S):
            await db.ping()
    except (TimeoutError, OSError, SQLAlchemyError):
        logger.warning("Readiness check failed: database unavailable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="unavailable")
    return ReadinessResponse(status="ok", database="ok")
