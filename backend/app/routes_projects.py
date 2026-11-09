from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import secrets

from app.database import get_db
from app.models import User, Workspace, Project, Canvas, Screen, DesignTokens
from app.schemas import ProjectCreate, ProjectOut, ScreenCreate, ScreenUpdate, ScreenOut
from app.routes_auth import get_current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Busca workspaces da organização do usuário
    ws_query = await db.execute(select(Workspace.id).where(Workspace.organization_id == current_user.organization_id))
    ws_ids = ws_query.scalars().all()

    if not ws_ids:
        return []

    # Busca projetos desses workspaces
    proj_query = await db.execute(
        select(Project)
        .where(Project.workspace_id.in_(ws_ids), Project.is_archived == False)
        .order_by(Project.updated_at.desc())
    )
    return proj_query.scalars().all()


@router.post("", response_model=ProjectOut)
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workspace_id = payload.workspace_id
    if not workspace_id:
        ws_res = await db.execute(
            select(Workspace).where(Workspace.organization_id == current_user.organization_id).limit(1)
        )
        ws = ws_res.scalars().first()
        if not ws:
            ws = Workspace(name="Geral", slug="geral", organization_id=current_user.organization_id)
            db.add(ws)
            await db.flush()
        workspace_id = ws.id

    import re, unicodedata
    clean_name = unicodedata.normalize('NFKD', payload.name).encode('ASCII', 'ignore').decode('ASCII')
    proj_slug = re.sub(r'[^a-zA-Z0-9]+', '-', clean_name).strip('-').lower() + f"-{secrets.token_hex(2)}"
    project = Project(
        name=payload.name,
        slug=proj_slug,
        description=payload.description or "",
        workspace_id=workspace_id,
    )
    db.add(project)
    await db.flush()

    # Cria Tokens padrão
    default_light = {
        "color-primary": "#0f766e",
        "color-bg": "#f8fafc",
        "color-surface": "#ffffff",
        "color-text": "#0f172a",
        "color-border": "#e2e8f0"
    }
    default_dark = {
        "color-primary": "#2dd4bf",
        "color-bg": "#0b1220",
        "color-surface": "#111a2e",
        "color-text": "#e2e8f0",
        "color-border": "#1e293b"
    }
    tokens = DesignTokens(
        project_id=project.id,
        light_tokens=default_light,
        dark_tokens=default_dark,
        shared_tokens={"radius-md": "8px", "font-body": "Inter, sans-serif"}
    )
    db.add(tokens)

    # Cria Canvas inicial
    canvas = Canvas(
        project_id=project.id,
        name="Principal",
        sort_order=0
    )
    db.add(canvas)
    await db.flush()

    # Cria Tela Principal inicial
    initial_html = (
        '<div class="flex flex-col items-center justify-center min-h-[500px] p-8 text-center" data-mb-id="root-hero">'
        '  <h1 class="text-4xl font-bold mb-4" data-mb-id="hero-title">Bem-vindo ao Mockbird v2</h1>'
        '  <p class="text-lg text-slate-500 max-w-md mb-6" data-mb-id="hero-desc">Este é o seu primeiro mock. Clique nos elementos para editar ou arraste para compor sua interface.</p>'
        '  <button class="px-6 py-3 bg-teal-600 text-white rounded-lg font-medium shadow-md hover:bg-teal-700 transition" data-mb-id="hero-cta">Começar Agora</button>'
        '</div>'
    )
    screen = Screen(
        canvas_id=canvas.id,
        name="Início",
        is_entry=True,  # ⭐ Tela Principal
        html_content=initial_html,
        css_content="",
        js_content="",
        width=1440,
        height=900
    )
    db.add(screen)
    await db.flush()

    project.entry_screen_id = screen.id
    canvas.entry_screen_id = screen.id

    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await _get_project_for_user(project_id, current_user, db)


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Exclui um projeto e todos os seus recursos vinculados (canvases, telas, tokens)."""
    project = await _get_project_for_user(project_id, current_user, db)
    await db.delete(project)
    await db.commit()
    return {"message": "Projeto excluído com sucesso", "project_id": project_id}



async def _get_project_for_user(project_id: str, current_user: User, db: AsyncSession) -> Project:
    """Carrega o projeto garantindo que pertence à organização do usuário (isolamento multi-tenant)."""
    result = await db.execute(
        select(Project)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(Project.id == project_id, Workspace.organization_id == current_user.organization_id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return project


@router.get("/{project_id}/screens", response_model=List[ScreenOut])
async def list_project_screens(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lista todas as telas do projeto (de todos os canvases), tela principal primeiro."""
    await _get_project_for_user(project_id, current_user, db)
    result = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id == project_id)
        .order_by(Screen.is_entry.desc(), Screen.created_at.asc())
    )
    return result.scalars().all()


@router.post("/{project_id}/screens", response_model=ScreenOut)
async def create_project_screen(
    project_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cria uma nova tela no primeiro canvas do projeto."""
    await _get_project_for_user(project_id, current_user, db)
    canvas_res = await db.execute(
        select(Canvas).where(Canvas.project_id == project_id).order_by(Canvas.sort_order.asc(), Canvas.created_at.asc()).limit(1)
    )
    canvas = canvas_res.scalars().first()
    if not canvas:
        canvas = Canvas(project_id=project_id, name="Principal")
        db.add(canvas)
        await db.flush()

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Nome da tela é obrigatório")

    screen = Screen(
        canvas_id=canvas.id,
        name=name,
        html_content=payload.get("html_content") or "",
        css_content=payload.get("css_content") or "",
        js_content=payload.get("js_content") or "",
    )
    db.add(screen)
    await db.commit()
    await db.refresh(screen)
    return screen
