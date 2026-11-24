from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, timedelta
import hashlib
import secrets

import logging

from app.database import get_db
from app.mailer import (
    EmailDeliveryError,
    EmailNotConfigured,
    build_link,
    get_email_settings,
    provider_ready,
    send_invite_email,
)
from app.models import User, Workspace, Organization, OrganizationInvite
from app.routes_auth import get_current_user, require_admin
from app.auth import hash_password
from app.timeutils import utcnow

router = APIRouter(prefix="/api/org", tags=["organization"])
logger = logging.getLogger(__name__)


class MemberInvite(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    role: str = "editor"  # admin, editor, viewer
    temporary_password: Optional[str] = None


class MemberRoleUpdate(BaseModel):
    role: str  # admin, editor, viewer


class MemberOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime
    invite_token: Optional[str] = None
    invite_url: Optional[str] = None
    email_sent: Optional[bool] = None

    class Config:
        from_attributes = True


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    name: Optional[str] = None


class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    organization_id: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/members", response_model=List[MemberOut])
async def list_members(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = await db.execute(
        select(User)
        .where(User.organization_id == current_user.organization_id)
        .order_by(User.created_at.asc())
    )
    return query.scalars().all()


@router.post("/members/invite", response_model=MemberOut)
async def invite_member(
    payload: MemberInvite,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    if payload.role not in ["admin", "editor", "viewer"]:
        raise HTTPException(status_code=400, detail="Papel de convite inválido. Permitidos: admin, editor, viewer")

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Usuário com este e-mail já existe")

    initial_password = payload.temporary_password if payload.temporary_password else secrets.token_urlsafe(12)
    resolved_name = (payload.name or payload.email.split('@')[0]).strip()
    new_user = User(
        organization_id=current_user.organization_id,
        email=payload.email,
        name=resolved_name,
        role=payload.role,
        password_hash=hash_password(initial_password),
        # O convite chega no e-mail; a posse da caixa já foi comprovada.
        email_verified=True,
        email_verified_at=utcnow(),
    )
    db.add(new_user)
    await db.flush()

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    invite = OrganizationInvite(
        organization_id=current_user.organization_id,
        email=payload.email,
        role=payload.role,
        token=token_hash,
        expires_at=utcnow() + timedelta(hours=48)
    )
    db.add(invite)
    await db.commit()
    await db.refresh(new_user)

    out = MemberOut.model_validate(new_user)
    out.invite_token = raw_token
    out.invite_url = f"/accept-invite?token={raw_token}"
    out.email_sent = False

    # Envio best-effort: se o e-mail falhar, o admin ainda recebe o link.
    try:
        email_settings = await get_email_settings(db)
        if provider_ready(email_settings):
            org = await db.get(Organization, current_user.organization_id)
            await send_invite_email(
                db,
                to=payload.email,
                inviter_name=current_user.name,
                organization_name=org.name if org else "sua organização",
                role=payload.role,
                url=build_link(email_settings, f"/accept-invite?token={raw_token}"),
            )
            out.email_sent = True
    except (EmailNotConfigured, EmailDeliveryError) as exc:
        logger.warning("Convite para %s não enviado por e-mail: %s", payload.email, exc)
    except Exception:
        logger.exception("Convite para %s: falha inesperada no envio", payload.email)

    return out


@router.post("/members/accept-invite")
async def accept_invite(
    payload: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db)
):
    token_hash = hashlib.sha256(payload.token.strip().encode("utf-8")).hexdigest()
    res = await db.execute(
        select(OrganizationInvite).where(
            OrganizationInvite.token == token_hash,
            OrganizationInvite.used_at.is_(None)
        )
    )
    invite = res.scalars().first()
    if not invite or invite.expires_at < utcnow():
        raise HTTPException(status_code=400, detail="Convite inválido ou expirado")

    user_res = await db.execute(select(User).where(User.email == invite.email))
    user = user_res.scalars().first()
    if not user:
        user = User(
            organization_id=invite.organization_id,
            email=invite.email,
            name=(payload.name or invite.email.split('@')[0]).strip(),
            role=invite.role,
            password_hash=hash_password(payload.password)
        )
        db.add(user)
    else:
        user.password_hash = hash_password(payload.password)
        if payload.name:
            user.name = payload.name.strip()

    invite.used_at = utcnow()
    await db.commit()
    return {"status": "success", "message": "Convite aceito com sucesso", "email": invite.email}


@router.get("/workspaces", response_model=List[WorkspaceOut])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = await db.execute(
        select(Workspace)
        .where(Workspace.organization_id == current_user.organization_id)
        .order_by(Workspace.created_at.asc())
    )
    return query.scalars().all()


@router.post("/workspaces", response_model=WorkspaceOut)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    ws_slug = payload.name.lower().replace(" ", "-") + f"-{secrets.token_hex(2)}"
    ws = Workspace(
        name=payload.name,
        slug=ws_slug,
        organization_id=current_user.organization_id
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


@router.patch("/members/{member_id}/role", response_model=MemberOut)
async def update_member_role(
    member_id: str,
    payload: MemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Apenas administradores podem alterar permissões")

    if payload.role not in ["admin", "editor", "viewer"]:
        raise HTTPException(status_code=400, detail="Papel inválido. Opções: admin, editor, viewer")

    res = await db.execute(
        select(User).where(User.id == member_id, User.organization_id == current_user.organization_id)
    )
    member = res.scalars().first()
    if not member:
        raise HTTPException(status_code=404, detail="Membro não encontrado")

    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Não é permitido alterar o papel do proprietário")

    member.role = payload.role
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/members/{member_id}")
async def remove_member(
    member_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Apenas administradores podem remover membros")

    if member_id == current_user.id:
        raise HTTPException(status_code=400, detail="Você não pode remover a si mesmo da organização")

    res = await db.execute(
        select(User).where(User.id == member_id, User.organization_id == current_user.organization_id)
    )
    member = res.scalars().first()
    if not member:
        raise HTTPException(status_code=404, detail="Membro não encontrado")

    if member.role == "owner":
        raise HTTPException(status_code=400, detail="O proprietário da organização não pode ser removido")

    await db.delete(member)
    await db.commit()
    return {"message": "Membro removido com sucesso", "member_id": member_id}

