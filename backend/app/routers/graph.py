"""Combined-graph endpoint (backend prompt §5/§11)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import get_session
from app.graph.service import get_graph_payload
from app.schemas import GraphResponse

router = APIRouter(prefix="/api/graph", tags=["graph"])


# The payload is built (or read back from Redis) already serialized; declaring
# `response_model` still runs it through GraphResponse, which is the point —
# it is a cheap standing guard that what ships matches the contract, including
# for graphs served straight out of cache.
@router.get("", response_model=GraphResponse)
async def get_graph(session: AsyncSession = Depends(get_session)) -> Any:
    return await get_graph_payload(session)
