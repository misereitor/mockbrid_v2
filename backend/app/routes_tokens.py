from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from typing import Dict, Any

from app.database import get_db
from app.models import User, DesignTokens, Project
from app.routes_auth import get_current_user, require_editor
from app.authz import authorize_project

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


async def _validate_project_ownership(project_id: str, current_user: User, db: AsyncSession, action: str = "read") -> Project:
    return await authorize_project(project_id, current_user, action, db)


class TokensUpdate(BaseModel):
    light_tokens: Dict[str, Any]
    dark_tokens: Dict[str, Any]
    shared_tokens: Dict[str, Any]


class TokensOut(BaseModel):
    id: str
    project_id: str
    light_tokens: Dict[str, Any]
    dark_tokens: Dict[str, Any]
    shared_tokens: Dict[str, Any]

    class Config:
        from_attributes = True


@router.get("/{project_id}", response_model=TokensOut)
async def get_project_tokens(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await _validate_project_ownership(project_id, current_user, db, action="read")
    result = await db.execute(select(DesignTokens).where(DesignTokens.project_id == project_id))
    tokens = result.scalars().first()
    if not tokens:
        # Se não existir, inicializa com padrão
        tokens = DesignTokens(
            project_id=project_id,
            light_tokens={
                "color-primary": "#0f766e",
                "color-bg": "#f8fafc",
                "color-surface": "#ffffff",
                "color-text": "#0f172a",
                "color-border": "#e2e8f0"
            },
            dark_tokens={
                "color-primary": "#2dd4bf",
                "color-bg": "#0b1220",
                "color-surface": "#111a2e",
                "color-text": "#e2e8f0",
                "color-border": "#1e293b"
            },
            shared_tokens={
                "radius-md": "8px",
                "font-body": "Inter, sans-serif"
            }
        )
        db.add(tokens)
        await db.commit()
        await db.refresh(tokens)

    return tokens


@router.put("/{project_id}", response_model=TokensOut)
async def update_project_tokens(
    project_id: str,
    payload: TokensUpdate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    await _validate_project_ownership(project_id, current_user, db, action="edit")
    result = await db.execute(select(DesignTokens).where(DesignTokens.project_id == project_id))
    tokens = result.scalars().first()
    if not tokens:
        tokens = DesignTokens(project_id=project_id)
        db.add(tokens)

    tokens.light_tokens = payload.light_tokens
    tokens.dark_tokens = payload.dark_tokens
    tokens.shared_tokens = payload.shared_tokens

    await db.commit()
    await db.refresh(tokens)
    return tokens

