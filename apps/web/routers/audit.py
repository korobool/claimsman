"""Global audit log endpoint.

Returns the most recent AuditLog rows, with optional filters by
entity, entity_id, actor, and action. Used by the /app/audit screen.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web.db import get_session
from apps.web.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(
    session: Annotated[AsyncSession, Depends(get_session)],
    entity: str | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    actor: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {"entries": [r.to_dict() for r in rows]}
