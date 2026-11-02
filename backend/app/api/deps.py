"""Shared FastAPI dependencies."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.db import Database


def get_db(request: Request) -> Database:
    return cast(Database, request.app.state.db)


DatabaseDep = Annotated[Database, Depends(get_db)]
