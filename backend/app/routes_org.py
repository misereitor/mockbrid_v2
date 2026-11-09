from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, timedelta
import secrets

from app.database import get_db
from app.models import User, Organization, Workspace, Project
from app.routes_auth import get_current_user
from app.auth import hash_password

router = APIRouter(prefix="/api/org", tags=["organization"])


class MemberInvite(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    role: str = "editor"  # admin, editor, viewer


class MemberRoleUpdate(BaseModel):
    role: str  # admin, editor, viewer


class MemberOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Apenas administradores podem convidar membros")

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Usuário com este e-mail já existe")

    temp_password = secrets.token_urlsafe(10)
    resolved_name = (payload.name or payload.email.split('@')[0]).strip()
    new_user = User(
        organization_id=current_user.organization_id,
        email=payload.email,
        name=resolved_name,
        role=payload.role,
        password_hash=hash_password(temp_password)
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


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
    current_user: User = Depends(get_current_user),
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

