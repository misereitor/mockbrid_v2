"""Upload e entrega de imagens usadas nas telas.

Sem dependência externa: os arquivos ficam em `ASSETS_DIR/<project_id>/`.
A entrega é liberada para membros do projeto e, para visitantes, apenas quando
o projeto está publicado ou possui share link ativo (URLs são UUIDs).
"""

import hashlib
import hmac
import logging
import re
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
from app.models import Asset, Canvas, Project, Screen, Session, ShareLink, User
from app.routes_auth import get_current_user, require_editor
from app.storage import ALLOWED_TYPES, asset_path, delete_asset, save_asset, sniff_image_type
from app.timeutils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assets"])

MAX_ASSET_BYTES = settings.MAX_ASSET_BYTES


def generate_asset_signature(asset_id: str) -> str:
    """Gera assinatura HMAC SHA-256 para permitir carregamento do asset em sandbox."""
    return hmac.new(settings.SECRET_KEY.encode(), f"asset:{asset_id}".encode(), hashlib.sha256).hexdigest()[:32]


def verify_asset_signature(asset_id: str, sig: str) -> bool:
    if not sig:
        return False
    expected = generate_asset_signature(asset_id)
    return hmac.compare_digest(expected, sig)


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
    sig = generate_asset_signature(asset.id)
    return AssetOut(
        id=asset.id,
        project_id=asset.project_id,
        original_name=asset.original_name,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        url=f"/api/assets/{asset.id}?sig={sig}",
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

    head = await file.read(512)
    content_type = sniff_image_type(head)
    if not content_type:
        raise HTTPException(
            status_code=415,
            detail="Formato não suportado. Envie PNG, JPEG, GIF, WebP ou SVG.",
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

    sig = request.query_params.get("sig", "")
    allowed = verify_asset_signature(asset_id, sig)
    if not allowed:
        user = await _optional_user(request, db)
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

    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Disposition": f'inline; filename="{asset.filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    if asset.content_type == "image/svg+xml":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"

    return FileResponse(
        path,
        media_type=asset.content_type,
        headers=headers,
    )


class ReplaceAssetUrlIn(BaseModel):
    old_url: str
    asset_id: str


@router.post("/api/projects/{project_id}/replace-asset-urls")
async def replace_asset_urls(
    project_id: str,
    payload: ReplaceAssetUrlIn,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    project = await authorize_project(project_id, current_user, "edit", db)
    res_asset = await db.execute(
        select(Asset).where(Asset.id == payload.asset_id, Asset.project_id == project.id)
    )
    asset = res_asset.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset não encontrado neste projeto")

    sig = generate_asset_signature(asset.id)
    new_url = f"/api/assets/{asset.id}?sig={sig}"

    res_screens = await db.execute(
        select(Screen).join(Canvas).where(Canvas.project_id == project.id)
    )
    screens = res_screens.scalars().all()
    count = 0
    old = payload.old_url.strip()
    for screen in screens:
        if old in screen.html_content:
            screen.html_content = screen.html_content.replace(old, new_url)
            count += 1

    await db.commit()
    logger.info("Substituído '%s' por '%s' em %d tela(s) do projeto %s", old, new_url, count, project.id)
    return {
        "message": f"URL substituída em {count} tela(s)",
        "replaced_screens": count,
        "new_url": new_url,
    }


@router.get("/api/projects/{project_id}/broken-images")
async def find_broken_images(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await authorize_project(project_id, current_user, "read", db)
    res_screens = await db.execute(
        select(Screen).join(Canvas).where(Canvas.project_id == project.id)
    )
    screens = res_screens.scalars().all()
    broken_urls = set()
    img_re = re.compile(r"""<img\b[^>]*src=["']([^"']+)["']""", re.IGNORECASE)
    for screen in screens:
        for match in img_re.finditer(screen.html_content or ""):
            src = match.group(1).strip()
            if not src.startswith(("/api/assets", "http://", "https://", "data:")):
                broken_urls.add(src)

    return {"broken_urls": sorted(list(broken_urls))}
