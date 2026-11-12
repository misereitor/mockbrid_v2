from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional

from app.models import User, Project, Workspace, Canvas, Screen, ProjectMember


ROLE_HIERARCHY = {
    "viewer": 1,
    "commenter": 2,
    "editor": 3,
    "admin": 4,
    "owner": 5,
}

ACTION_MIN_ROLE = {
    "read": "viewer",
    "comment": "commenter",
    "edit": "editor",
    "admin": "admin",
    "delete": "admin",
}


async def get_effective_project_role(
    project: Project,
    user: User,
    db: AsyncSession,
    organization_id: Optional[str] = None
) -> Optional[str]:
    """Calcula o papel efetivo do usuário em um projeto específico,
    respeitando tenant, propriedade, membros diretos e visibilidade."""
    # 1. Tenant Check
    if organization_id and organization_id != user.organization_id:
        return None

    # 2. Dono ou Administrador da Organização tem controle total
    if user.role in ["owner", "admin"]:
        return "admin"

    # 3. Dono do Projeto tem papel admin no projeto
    if project.owner_id and project.owner_id == user.id:
        return "admin"

    # 4. Checa atribuição direta na tabela project_members
    member_res = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id
        )
    )
    pm = member_res.scalars().first()
    if pm:
        return pm.role

    # 5. Se o projeto for público para a organização ('org')
    if project.visibility == "org":
        return user.role  # Herda seu papel da organização (ex: editor ou viewer)

    # 6. Se for 'private' e o usuário não for dono nem membro: sem acesso
    return None


async def authorize_project(
    project_id: str,
    user: User,
    action: str,
    db: AsyncSession
) -> Project:
    """Autoriza o acesso do usuário ao projeto especificado para a ação solicitada.
    Lança 404 se não encontrado ou invisível (prevenindo enumeração/IDOR).
    Lança 403 se visível mas sem permissão suficiente."""
    query = await db.execute(
        select(Project, Workspace.organization_id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(
            Project.id == project_id,
            Workspace.organization_id == user.organization_id
        )
    )
    row = query.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")

    project, org_id = row[0], row[1]
    effective_role = await get_effective_project_role(project, user, db, organization_id=org_id)
    if not effective_role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")

    min_role_needed = ACTION_MIN_ROLE.get(action, "viewer")
    user_level = ROLE_HIERARCHY.get(effective_role, 0)
    needed_level = ROLE_HIERARCHY.get(min_role_needed, 1)

    if user_level < needed_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permissão insuficiente no projeto para a ação '{action}'. Papel necessário: {min_role_needed}, seu papel: {effective_role}."
        )

    return project


async def authorize_screen(
    screen_id: str,
    user: User,
    action: str,
    db: AsyncSession
) -> Screen:
    """Valida o acesso à tela garantindo a autorização sobre o projeto ao qual pertence."""
    query = await db.execute(
        select(Screen, Project)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .join(Project, Project.id == Canvas.project_id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(
            Screen.id == screen_id,
            Workspace.organization_id == user.organization_id
        )
    )
    row = query.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tela não encontrada")

    screen, project = row[0], row[1]
    # Valida ação no projeto pai
    await authorize_project(project.id, user, action, db)
    return screen