from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog


async def record_audit(
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    actor_id: Optional[int] = None,
    outcome: str = "success",
    detail: Optional[dict[str, Any] | str] = None,
    request: Optional[Request] = None,
) -> None:
    if isinstance(detail, dict):
        detail_value = json.dumps(detail, ensure_ascii=True, separators=(",", ":"))
    else:
        detail_value = detail
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            detail=detail_value,
            ip_address=request.client.host if request and request.client else None,
        )
    )
