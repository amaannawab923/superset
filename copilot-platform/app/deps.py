"""Request dependencies: feature gate + auth principal.

Real deployment: @protect() equivalent — verify the JWT, enforce RBAC, resolve
(user_id, workspace_id) from the token. The base shell uses a dev principal from
settings so the API is exercisable without an auth server.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException

from .config import Settings, get_settings


@dataclass
class Principal:
    user_id: int
    workspace_id: str


def require_feature(settings: Settings = Depends(get_settings)) -> None:
    # A3: COPILOT_WS_ENABLED off -> 404 (feature is invisible, not forbidden).
    if not settings.copilot_ws_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def current_principal(settings: Settings = Depends(get_settings)) -> Principal:
    return Principal(
        user_id=settings.copilot_dev_user_id,
        workspace_id=settings.copilot_dev_workspace_id,
    )
