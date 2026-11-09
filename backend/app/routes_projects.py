from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import secrets

from app.database import get_db
from app.models import User, Workspace, Project, Canvas, Screen, DesignTokens
from app.schemas import ProjectCreate, ProjectOut, ScreenCreate, ScreenUpdate, ScreenOut
from app.routes_auth import get_current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Busca workspaces da organização do usuário
    ws_query = await db.execute(select(Workspace.id).where(Workspace.organization_id == current_user.organization_id))
    ws_ids = ws_query.scalars().all()

    if not ws_ids:
        return []

    # Busca projetos desses workspaces com busca opcional
    query = select(Project).where(Project.workspace_id.in_(ws_ids), Project.is_archived == False)
    if q and q.strip():
        query = query.where(Project.name.ilike(f"%{q.strip()}%"))

    proj_query = await db.execute(query.order_by(Project.updated_at.desc()))
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


@router.post("/{project_id}/duplicate", response_model=ProjectOut)
async def duplicate_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Duplica um projeto inteiro incluindo canvases, telas e design tokens."""
    orig_proj = await _get_project_for_user(project_id, current_user, db)

    new_slug = f"{orig_proj.slug}-copia-{secrets.token_hex(2)}"
    new_proj = Project(
        name=f"{orig_proj.name} (Cópia)",
        slug=new_slug,
        description=orig_proj.description,
        workspace_id=orig_proj.workspace_id,
    )
    db.add(new_proj)
    await db.flush()

    # Copia Tokens
    tokens_res = await db.execute(select(DesignTokens).where(DesignTokens.project_id == orig_proj.id))
    orig_tokens = tokens_res.scalars().first()
    if orig_tokens:
        new_tokens = DesignTokens(
            project_id=new_proj.id,
            light_tokens=orig_tokens.light_tokens,
            dark_tokens=orig_tokens.dark_tokens,
        )
        db.add(new_tokens)

    # Copia Canvases e Telas
    canvas_map = {}
    canvases_res = await db.execute(select(Canvas).where(Canvas.project_id == orig_proj.id))
    for c in canvases_res.scalars().all():
        new_canvas = Canvas(
            project_id=new_proj.id,
            name=c.name,
            sort_order=c.sort_order
        )
        db.add(new_canvas)
        await db.flush()
        canvas_map[c.id] = new_canvas.id

        # Copia telas deste canvas
        screens_res = await db.execute(select(Screen).where(Screen.canvas_id == c.id))
        for s in screens_res.scalars().all():
            new_screen = Screen(
                canvas_id=new_canvas.id,
                name=s.name,
                is_entry=s.is_entry,
                screen_kind=s.screen_kind,
                device_type=s.device_type,
                width=s.width,
                height=s.height,
                pos_x=s.pos_x,
                pos_y=s.pos_y,
                html_content=s.html_content,
                css_content=s.css_content,
                js_content=s.js_content,
                transition=s.transition,
                current_revision=1
            )
            db.add(new_screen)
            await db.flush()
            if s.is_entry:
                new_proj.entry_screen_id = new_screen.id

    await db.commit()
    await db.refresh(new_proj)
    return new_proj


@router.get("/{project_id}/export/bundle")
async def export_project_bundle(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Dev Mode: Retorna mapa consolidado de todas as telas, tokens e templates do projeto."""
    project = await _get_project_for_user(project_id, current_user, db)

    # Tokens
    t_query = await db.execute(select(DesignTokens).where(DesignTokens.project_id == project_id))
    tokens = t_query.scalars().first()

    # Telas
    screens_res = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id == project_id)
        .order_by(Screen.is_entry.desc(), Screen.created_at.asc())
    )
    screens = screens_res.scalars().all()

    bundle_screens = []
    for s in screens:
        component_name = "".join(w.capitalize() for w in s.name.split()) + "Screen"
        clean_jsx = s.html_content.replace('class="', 'className="')
        bundle_screens.append({
            "id": s.id,
            "name": s.name,
            "is_entry": s.is_entry,
            "html": s.html_content,
            "css": s.css_content,
            "react_component": f"export function {component_name}() {{\n  return (\n    {clean_jsx}\n  );\n}}"
        })

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "slug": project.slug
        },
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {}
        },
        "screens": bundle_screens
    }
