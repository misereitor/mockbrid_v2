"""Upload e entrega de imagens usadas nas telas.

Sem dependência externa: os arquivos ficam em `ASSETS_DIR/<project_id>/`.
A entrega é liberada para membros do projeto e, para visitantes, apenas quando
o projeto está publicado ou possui share link ativo (URLs são UUIDs).
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth import decode_access_token, hash_session_token
from app.authz import authorize_project
from app.config import settings
from app.database import get_db
from app.models import Asset, Project, Session, ShareLink, User
from app.routes_auth import get_current_user, require_editor
from app.storage import ALLOWED_TYPES, asset_path, delete_asset, save_asset, sniff_image_type
from app.timeutils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assets"])

MAX_ASSET_BYTES = settings.MAX_ASSET_BYTES


class AssetOut(BaseModel):
    id: str
    project_id: str
    original_name: str
    content_type: str
    size_bytes: int
    url: str
    created_at: datetime

    class Config:
        from_attributes = True


def _to_out(asset: Asset) -> AssetOut:
    return AssetOut(
        id=asset.id,
        project_id=asset.project_id,
        original_name=asset.original_name,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        url=f"/api/assets/{asset.id}",
        created_at=asset.created_at,
    )


@router.post("/api/projects/{project_id}/assets", response_model=AssetOut)
async def upload_asset(
    project_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    project = await authorize_project(project_id, current_user, "edit", db)

    head = await file.read(32)
    content_type = sniff_image_type(head)
    if not content_type:
        raise HTTPException(
            status_code=415,
            detail="Formato não suportado. Envie PNG, JPEG, GIF ou WebP.",
        )

    data = head + await file.read(MAX_ASSET_BYTES + 1 - len(head))
    if len(data) > MAX_ASSET_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo maior que o limite de {MAX_ASSET_BYTES // (1024 * 1024)} MB",
        )

    filename = save_asset(project.id, data, content_type)
    asset = Asset(
        project_id=project.id,
        uploaded_by=current_user.id,
        filename=filename,
        original_name=(file.filename or "imagem")[:255],
        content_type=content_type,
        size_bytes=len(data),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    logger.info("Asset %s enviado para o projeto %s (%s bytes)", asset.id, project.id, len(data))
    return _to_out(asset)


@router.get("/api/projects/{project_id}/assets", response_model=List[AssetOut])
async def list_assets(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "read", db)
    limit = max(1, min(limit, 200))
    res = await db.execute(
        select(Asset)
        .where(Asset.project_id == project_id)
        .order_by(Asset.created_at.desc())
        .limit(limit)
        .offset(max(0, offset))
    )
    return [_to_out(a) for a in res.scalars().all()]


@router.delete("/api/projects/{project_id}/assets/{asset_id}")
async def remove_asset(
    project_id: str,
    asset_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "edit", db)
    res = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id)
    )
    asset = res.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset não encontrado")
    delete_asset(project_id, asset.filename)
    await db.delete(asset)
    await db.commit()
    return {"message": "Asset removido", "asset_id": asset_id}


async def _optional_user(request: Request, db: AsyncSession) -> Optional[User]:
    token = request.cookies.get("mockbird_token")
    if not token:
        header = request.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            token = header[len("Bearer "):]
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    session_res = await db.execute(
        select(Session).where(Session.token == hash_session_token(token))
    )
    session = session_res.scalars().first()
    if not session or session.expires_at < utcnow():
        return None
    user_res = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_res.scalars().first()
    if not user or not user.is_active:
        return None
    return user


async def _project_is_public(project_id: str, db: AsyncSession) -> bool:
    res = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.is_archived == False,  # noqa: E712
            Project.is_published == True,  # noqa: E712
        )
    )
    if res.scalars().first():
        return True
    links = await db.execute(select(ShareLink).where(ShareLink.project_id == project_id))
    now = utcnow()
    return any(
        link.expires_at is None or link.expires_at > now
        for link in links.scalars().all()
    )


@router.get("/api/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = res.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset não encontrado")

    user = await _optional_user(request, db)
    allowed = False
    if user:
        try:
            await authorize_project(asset.project_id, user, "read", db)
            allowed = True
        except HTTPException:
            allowed = False
    if not allowed:
        allowed = await _project_is_public(asset.project_id, db)
    if not allowed:
        raise HTTPException(status_code=404, detail="Asset não encontrado")

    path = asset_path(asset.project_id, asset.filename)
    if not path:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    if asset.content_type not in ALLOWED_TYPES:  # defesa em profundidade
        raise HTTPException(status_code=415, detail="Tipo de arquivo não permitido")

    return FileResponse(
        path,
        media_type=asset.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": f'inline; filename="{asset.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
