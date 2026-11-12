"""Share links de apresentação: criação, listagem e revogação.

O link público (`/p/<slug>`) só entrega conteúdo quando existe um ShareLink
ativo (não expirado/revogado) ou quando o projeto foi explicitamente publicado.
"""

import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth import hash_password
from app.authz import authorize_project
from app.database import get_db
from app.models import ShareLink, User
from app.routes_auth import get_current_user, require_editor
from app.schemas import ShareLinkCreate, ShareLinkOut
from app.timeutils import utcnow

router = APIRouter(prefix="/api/projects", tags=["share"])


def _to_out(link: ShareLink) -> ShareLinkOut:
    return ShareLinkOut(
        id=link.id,
        project_id=link.project_id,
        slug=link.slug,
        allow_comments=link.allow_comments,
        expires_at=link.expires_at,
        view_count=link.view_count,
        has_password=bool(link.password_hash),
        created_at=link.created_at,
    )


@router.get("/{project_id}/share-links", response_model=List[ShareLinkOut])
async def list_share_links(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "admin", db)
    res = await db.execute(
        select(ShareLink)
        .where(ShareLink.project_id == project_id)
        .order_by(ShareLink.created_at.desc())
    )
    return [_to_out(link) for link in res.scalars().all()]


@router.post("/{project_id}/share-links", response_model=ShareLinkOut)
async def create_share_link(
    project_id: str,
    payload: ShareLinkCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "admin", db)

    slug = secrets.token_urlsafe(12)
    expires_at = None
    if payload.expires_in_days:
        from datetime import timedelta

        expires_at = utcnow() + timedelta(days=payload.expires_in_days)

    link = ShareLink(
        project_id=project_id,
        slug=slug,
        password_hash=hash_password(payload.password) if payload.password else None,
        allow_comments=payload.allow_comments,
        expires_at=expires_at,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return _to_out(link)


@router.delete("/{project_id}/share-links/{link_id}")
async def revoke_share_link(
    project_id: str,
    link_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "admin", db)
    res = await db.execute(
        select(ShareLink).where(
            ShareLink.id == link_id,
            ShareLink.project_id == project_id,
        )
    )
    link = res.scalars().first()
    if not link:
        raise HTTPException(status_code=404, detail="Link de compartilhamento não encontrado")
    await db.delete(link)
    await db.commit()
    return {"message": "Link revogado com sucesso", "link_id": link_id}


@router.post("/{project_id}/publish")
async def publish_project(
    project_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Publica o projeto, habilitando /p/<slug> sem senha."""
    project = await authorize_project(project_id, current_user, "admin", db)
    project.is_published = True
    await db.commit()
    await db.refresh(project)
    return {"slug": project.slug, "url": f"/p/{project.slug}", "is_published": True}


@router.delete("/{project_id}/publish")
async def unpublish_project(
    project_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    project = await authorize_project(project_id, current_user, "admin", db)
    project.is_published = False
    await db.commit()
    return {"is_published": False, "message": "Projeto despublicado; apenas share links ativos seguem acessíveis"}
