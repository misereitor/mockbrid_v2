"""Share links de apresentação: criação, listagem, edição e revogação.

O link público (`/p/<slug>`) só entrega conteúdo quando existe um ShareLink ativo
(não expirado/revogado). O slug do link é um token aleatório de 96 bits; o slug
do projeto nunca abre a apresentação pública.

Níveis de acesso (`access_mode`):
- `anyone`: qualquer pessoa com o link (com senha opcional);
- `org`: exige login e acesso de leitura ao projeto.
"""

import secrets
from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth import hash_password
from app.authz import authorize_project
from app.database import get_db
from app.models import ShareLink, User
from app.presentation import NoScreenError, build_presentation_payload
from app.routes_auth import get_current_user, require_editor
from app.schemas import ShareLinkCreate, ShareLinkOut, ShareLinkUpdate
from app.timeutils import utcnow

router = APIRouter(prefix="/api/projects", tags=["share"])


def _to_out(link: ShareLink) -> ShareLinkOut:
    return ShareLinkOut(
        id=link.id,
        project_id=link.project_id,
        slug=link.slug,
        allow_comments=link.allow_comments,
        access_mode=link.access_mode or "anyone",
        label=link.label,
        expires_at=link.expires_at,
        view_count=link.view_count,
        has_password=bool(link.password_hash),
        created_at=link.created_at,
    )


def _clean_label(label: str | None) -> str | None:
    label = (label or "").strip()
    return label or None


async def _get_link(project_id: str, link_id: str, db: AsyncSession) -> ShareLink:
    res = await db.execute(
        select(ShareLink).where(
            ShareLink.id == link_id,
            ShareLink.project_id == project_id,
        )
    )
    link = res.scalars().first()
    if not link:
        raise HTTPException(status_code=404, detail="Link de compartilhamento não encontrado")
    return link


@router.get("/{project_id}/presentation")
async def get_private_presentation(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pré-visualização privada: o botão "Apresentar" abre isto, sem publicar nada.

    Exige sessão com acesso de leitura ao projeto. Não cria link, não conta
    visualização e não libera comentários de visitante.
    """
    project = await authorize_project(project_id, current_user, "read", db)
    try:
        return await build_presentation_payload(project, db, allow_comments=False)
    except NoScreenError:
        raise HTTPException(status_code=404, detail="Nenhuma tela configurada para este projeto")


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

    expires_at = None
    if payload.expires_in_days:
        expires_at = utcnow() + timedelta(days=payload.expires_in_days)

    link = ShareLink(
        project_id=project_id,
        slug=secrets.token_urlsafe(12),
        password_hash=hash_password(payload.password) if payload.password else None,
        allow_comments=payload.allow_comments,
        access_mode=payload.access_mode,
        label=_clean_label(payload.label),
        expires_at=expires_at,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return _to_out(link)


@router.patch("/{project_id}/share-links/{link_id}", response_model=ShareLinkOut)
async def update_share_link(
    project_id: str,
    link_id: str,
    payload: ShareLinkUpdate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Muda as permissões de um link existente sem trocar a URL."""
    await authorize_project(project_id, current_user, "admin", db)
    link = await _get_link(project_id, link_id, db)

    changes = payload.model_dump(exclude_unset=True)

    if "access_mode" in changes and payload.access_mode is not None:
        link.access_mode = payload.access_mode
    if "allow_comments" in changes and payload.allow_comments is not None:
        link.allow_comments = payload.allow_comments
    if "label" in changes:
        link.label = _clean_label(payload.label)
    if "password" in changes and payload.password is not None:
        # String vazia remove a senha; ausente mantém a atual.
        link.password_hash = hash_password(payload.password) if payload.password else None
    if "expires_in_days" in changes and payload.expires_in_days is not None:
        # 0 = sem validade.
        link.expires_at = (
            utcnow() + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days
            else None
        )

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
    link = await _get_link(project_id, link_id, db)
    await db.delete(link)
    await db.commit()
    return {"message": "Link revogado com sucesso", "link_id": link_id}


# ---------------------------------------------------------------------------
# Publicação permanente descontinuada
# ---------------------------------------------------------------------------
# `POST /publish` tornava o projeto público para sempre, sem senha e pelo slug do
# projeto (curto e adivinhável). Agora compartilhar é uma ação explícita, com
# permissões, pelos share links.

_PUBLISH_GONE = (
    "A publicação permanente foi descontinuada. Crie um link em "
    "POST /api/projects/{id}/share-links (com senha, validade e nível de acesso)."
)


@router.post("/{project_id}/publish", status_code=410)
async def publish_project(
    project_id: str,
    current_user: User = Depends(require_editor),
):
    raise HTTPException(status_code=410, detail=_PUBLISH_GONE)


@router.delete("/{project_id}/publish")
async def unpublish_project(
    project_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Mantido por compatibilidade: garante que o projeto não está publicado."""
    project = await authorize_project(project_id, current_user, "admin", db)
    project.is_published = False
    await db.commit()
    return {"is_published": False, "message": "Projeto não publicado; use share links para compartilhar"}
