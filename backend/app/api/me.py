import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUserDep

router = APIRouter(tags=["me"])


class MeRead(BaseModel):
    id: uuid.UUID


@router.get("/api/me")
async def me(user: CurrentUserDep) -> MeRead:
    return MeRead(id=user.id)
