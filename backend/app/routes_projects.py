from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pathlib import Path
from typing import Any, Dict, List, Optional
import secrets

from app.database import get_db
from app.models import (
    User,
    Workspace,
    Project,
    Canvas,
    Screen,
    DesignTokens,
    DataScenario,
    ScreenRevision,
    ProjectMember,
    Asset,
)
from app.schemas import (
    DesignImportOut,
    ProjectCreate,
    ProjectOut,
    ScreenOut,
    ProjectMemberCreate,
    ProjectMemberOut,
    ProjectVisibilityUpdate,
)
from app.design_corpus import (
    DesignCorpusError,
    build_design_corpus,
    parse_design_corpus,
)
from app.routes_auth import get_current_user, require_editor
from app.authz import authorize_project
from app.jsx import html_to_jsx
from app.storage import save_asset, sniff_image_type
from app.routes_assets import generate_asset_signature

router = APIRouter(prefix="/api/projects", tags=["projects"])

DEFAULT_LIGHT_TOKENS = {
    "color-primary": "#0f766e",
    "color-bg": "#f8fafc",
    "color-surface": "#ffffff",
    "color-text": "#0f172a",
    "color-border": "#e2e8f0",
}
DEFAULT_DARK_TOKENS = {
    "color-primary": "#2dd4bf",
    "color-bg": "#0b1220",
    "color-surface": "#111a2e",
    "color-text": "#e2e8f0",
    "color-border": "#1e293b",
}
DEFAULT_SHARED_TOKENS = {"radius-md": "8px", "font-body": "Inter, sans-serif"}


async def _create_project_shell(
    db: AsyncSession,
    current_user: User,
    name: str,
    description: str = "",
    visibility: str = "private",
    workspace_id: Optional[str] = None,
    tokens_light: Optional[Dict[str, Any]] = None,
    tokens_dark: Optional[Dict[str, Any]] = None,
    tokens_shared: Optional[Dict[str, Any]] = None,
) -> Project:
    """Cria workspace (se preciso), projeto e tokens — sem canvas nem telas."""
    if not workspace_id:
        ws_res = await db.execute(
            select(Workspace)
            .where(Workspace.organization_id == current_user.organization_id)
            .limit(1)
        )
        ws = ws_res.scalars().first()
        if not ws:
            ws = Workspace(
                name="Geral", slug="geral", organization_id=current_user.organization_id
            )
            db.add(ws)
            await db.flush()
        workspace_id = ws.id

    import re
    import unicodedata

    clean_name = (
        unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("ASCII")
    )
    proj_slug = (
        re.sub(r"[^a-zA-Z0-9]+", "-", clean_name).strip("-").lower()
        + f"-{secrets.token_hex(2)}"
    )
    project = Project(
        name=name,
        slug=proj_slug,
        description=description or "",
        workspace_id=workspace_id,
        owner_id=current_user.id,
        visibility=visibility or "private",
    )
    db.add(project)
    await db.flush()

    tokens = DesignTokens(
        project_id=project.id,
        light_tokens=tokens_light or dict(DEFAULT_LIGHT_TOKENS),
        dark_tokens=tokens_dark or dict(DEFAULT_DARK_TOKENS),
        shared_tokens=tokens_shared or dict(DEFAULT_SHARED_TOKENS),
    )
    db.add(tokens)
    await db.flush()
    return project


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Busca workspaces da organização do usuário
    ws_query = await db.execute(
        select(Workspace.id).where(
            Workspace.organization_id == current_user.organization_id
        )
    )
    ws_ids = ws_query.scalars().all()

    if not ws_ids:
        return []

    # Se for admin ou owner da organização, vê todos os projetos
    if current_user.role in ["owner", "admin"]:
        query = select(Project).where(
            Project.workspace_id.in_(ws_ids), Project.is_archived.is_(False)
        )
    else:
        # Busca IDs de projetos onde o usuário é membro explicitamente
        m_query = await db.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == current_user.id
            )
        )
        member_proj_ids = m_query.scalars().all()

        query = select(Project).where(
            Project.workspace_id.in_(ws_ids),
            Project.is_archived.is_(False),
            (Project.visibility == "org")
            | (Project.owner_id == current_user.id)
            | (Project.id.in_(member_proj_ids)),
        )

    if q and q.strip():
        query = query.where(Project.name.ilike(f"%{q.strip()}%"))

    query = (
        query.order_by(Project.updated_at.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 200))
    )
    proj_query = await db.execute(query)
    return proj_query.scalars().all()


@router.post("", response_model=ProjectOut)
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    project = await _create_project_shell(
        db,
        current_user,
        payload.name,
        payload.description or "",
        payload.visibility or "private",
        workspace_id=payload.workspace_id,
    )

    # Cria Canvas inicial
    canvas = Canvas(project_id=project.id, name="Principal", sort_order=0)
    db.add(canvas)
    await db.flush()

    # Cria Tela Principal inicial
    initial_html = (
        '<div class="flex flex-col items-center justify-center min-h-[500px] p-8 text-center" data-mb-id="root-hero">'
        '  <h1 class="text-4xl font-bold mb-4" data-mb-id="hero-title">Bem-vindo ao Mockbird v2</h1>'
        '  <p class="text-lg text-slate-500 max-w-md mb-6" data-mb-id="hero-desc">Este é o seu primeiro mock. Clique nos elementos para editar ou arraste para compor sua interface.</p>'
        '  <button class="px-6 py-3 bg-teal-600 text-white rounded-lg font-medium shadow-md hover:bg-teal-700 transition" data-mb-id="hero-cta">Começar Agora</button>'
        "</div>"
    )
    screen = Screen(
        canvas_id=canvas.id,
        name="Início",
        is_entry=True,  # ⭐ Tela Principal
        html_content=initial_html,
        css_content="",
        js_content="",
        width=1440,
        height=900,
    )
    db.add(screen)
    await db.flush()

    project.entry_screen_id = screen.id
    canvas.entry_screen_id = screen.id

    await db.commit()
    await db.refresh(project)
    return project


@router.post("/import/design", response_model=DesignImportOut)
async def import_design_corpus(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Importa um ZIP com a pasta `design/` do Mockbird v1 como um novo projeto."""
    blob = await file.read()
    try:
        parsed = parse_design_corpus(blob)
    except DesignCorpusError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw_name = (name or "").strip()
    if not raw_name:
        raw_name = (
            Path(file.filename or "").stem.replace("_", " ").replace("-", " ").strip()
        )
    if not raw_name or raw_name.lower() in {"design", "zip", "corpus"}:
        raw_name = "Projeto importado"

    tokens = parsed["tokens"]
    project = await _create_project_shell(
        db,
        current_user,
        raw_name,
        "Importado do corpus design/ do Mockbird v1.",
        tokens_light=tokens["light"] or None,
        tokens_dark=tokens["dark"] or None,
        tokens_shared=tokens["shared"] or None,
    )

    imported_assets: Dict[str, str] = {}
    from urllib.parse import quote

    for asset_path_in_zip, asset_bytes in parsed.get("assets", {}).items():
        content_type = sniff_image_type(asset_bytes[:512])
        if not content_type:
            lowered = asset_path_in_zip.lower()
            if lowered.endswith(".svg"):
                content_type = "image/svg+xml"
            elif lowered.endswith(".png"):
                content_type = "image/png"
            elif lowered.endswith((".jpg", ".jpeg")):
                content_type = "image/jpeg"
            elif lowered.endswith(".webp"):
                content_type = "image/webp"
            elif lowered.endswith(".gif"):
                content_type = "image/gif"
        if not content_type:
            continue

        filename = save_asset(project.id, asset_bytes, content_type)
        base_name = Path(asset_path_in_zip).name[:255]
        asset_obj = Asset(
            project_id=project.id,
            uploaded_by=current_user.id,
            filename=filename,
            original_name=base_name,
            content_type=content_type,
            size_bytes=len(asset_bytes),
        )
        db.add(asset_obj)
        await db.flush()
        sig = generate_asset_signature(asset_obj.id)
        new_url = f"/api/assets/{asset_obj.id}?sig={sig}"
        imported_assets[asset_path_in_zip] = new_url
        imported_assets[base_name] = new_url
        imported_assets[f"../{base_name}"] = new_url
        imported_assets[f"./{base_name}"] = new_url
        encoded_base = quote(base_name)
        imported_assets[f"../{encoded_base}"] = new_url
        imported_assets[f"./{encoded_base}"] = new_url

    entry_screen_id: Optional[str] = None
    screen_total = 0
    for order, canvas_data in enumerate(parsed["canvases"]):
        canvas = Canvas(
            project_id=project.id,
            name=canvas_data["name"][:255],
            sort_order=order,
        )
        db.add(canvas)
        await db.flush()

        first_screen: Optional[Screen] = None
        for index, data in enumerate(canvas_data["screens"]):
            screen_html = data["html_content"]
            for old_ref, new_url in imported_assets.items():
                if old_ref in screen_html:
                    screen_html = screen_html.replace(
                        f'"{old_ref}"', f'"{new_url}"'
                    ).replace(f"'{old_ref}'", f"'{new_url}'")

            screen = Screen(
                canvas_id=canvas.id,
                name=data["name"][:255],
                is_entry=(index == 0),
                screen_kind=data.get("screen_kind") or "page",
                device_type=data.get("device_type") or "desktop",
                width=data["width"],
                height=data["height"],
                pos_x=index * 40,
                html_content=screen_html,
            )
            db.add(screen)
            await db.flush()
            if first_screen is None:
                first_screen = screen
            screen_total += 1

        if first_screen is not None:
            canvas.entry_screen_id = first_screen.id
            if entry_screen_id is None:
                entry_screen_id = first_screen.id

    project.entry_screen_id = entry_screen_id
    await db.commit()
    await db.refresh(project)

    return DesignImportOut(
        project=project,
        canvases=len(parsed["canvases"]),
        screens=screen_total,
        warnings=parsed["warnings"],
    )

    canvas = Canvas(project_id=project.id, name="Principal", sort_order=0)
    db.add(canvas)
    await db.flush()

    # Cria Tela Principal inicial
    initial_html = (
        '<div class="flex flex-col items-center justify-center min-h-[500px] p-8 text-center" data-mb-id="root-hero">'
        '  <h1 class="text-4xl font-bold mb-4" data-mb-id="hero-title">Bem-vindo ao Mockbird v2</h1>'
        '  <p class="text-lg text-slate-500 max-w-md mb-6" data-mb-id="hero-desc">Este é o seu primeiro mock. Clique nos elementos para editar ou arraste para compor sua interface.</p>'
        '  <button class="px-6 py-3 bg-teal-600 text-white rounded-lg font-medium shadow-md hover:bg-teal-700 transition" data-mb-id="hero-cta">Começar Agora</button>'
        "</div>"
    )
    screen = Screen(
        canvas_id=canvas.id,
        name="Início",
        is_entry=True,  # ⭐ Tela Principal
        html_content=initial_html,
        css_content="",
        js_content="",
        width=1440,
        height=900,
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
    db: AsyncSession = Depends(get_db),
):
    return await _get_project_for_user(project_id, current_user, db)


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Exclui um projeto e todos os seus recursos vinculados (canvases, telas, tokens).

    A autorização é a mesma das demais ações (admin do projeto ou da organização),
    em vez de exigir admin global da organização."""
    project = await _get_project_for_user(project_id, current_user, db, action="delete")
    await db.delete(project)
    await db.commit()
    return {"message": "Projeto excluído com sucesso", "project_id": project_id}


async def _get_project_for_user(
    project_id: str, current_user: User, db: AsyncSession, action: str = "read"
) -> Project:
    """Carrega o projeto garantindo que pertence à organização do usuário e respeita regras de visibilidade e papel."""
    return await authorize_project(project_id, current_user, action, db)


@router.patch("/{project_id}/visibility", response_model=ProjectOut)
async def update_project_visibility(
    project_id: str,
    payload: ProjectVisibilityUpdate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    project = await authorize_project(project_id, current_user, "admin", db)
    if payload.visibility not in ["private", "org"]:
        raise HTTPException(
            status_code=400, detail="Visibilidade inválida. Opções: 'private', 'org'"
        )
    project.visibility = payload.visibility
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}/members", response_model=List[ProjectMemberOut])
async def list_project_members(
    project_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "read", db)
    res = await db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .offset(max(0, offset))
        .limit(min(max(1, limit), 200))
    )
    members_out = []
    for pm, u in res.all():
        out = ProjectMemberOut.model_validate(pm)
        out.user_name = u.name
        out.user_email = u.email
        members_out.append(out)
    return members_out


@router.post("/{project_id}/members", response_model=ProjectMemberOut)
async def add_project_member(
    project_id: str,
    payload: ProjectMemberCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "admin", db)

    user_res = await db.execute(
        select(User).where(
            User.id == payload.user_id,
            User.organization_id == current_user.organization_id,
        )
    )
    target_user = user_res.scalars().first()
    if not target_user:
        raise HTTPException(
            status_code=404, detail="Usuário não encontrado na organização"
        )

    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == payload.user_id,
        )
    )
    pm = existing.scalars().first()
    if pm:
        pm.role = payload.role
    else:
        pm = ProjectMember(
            project_id=project_id, user_id=payload.user_id, role=payload.role
        )
        db.add(pm)

    await db.commit()
    await db.refresh(pm)
    out = ProjectMemberOut.model_validate(pm)
    out.user_name = target_user.name
    out.user_email = target_user.email
    return out


@router.delete("/{project_id}/members/{user_id}")
async def remove_project_member(
    project_id: str,
    user_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    await authorize_project(project_id, current_user, "admin", db)
    res = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    pm = res.scalars().first()
    if not pm:
        raise HTTPException(status_code=404, detail="Membro não encontrado no projeto")

    await db.delete(pm)
    await db.commit()
    return {"message": "Membro removido do projeto com sucesso"}


@router.get("/{project_id}/screens", response_model=List[ScreenOut])
async def list_project_screens(
    project_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista todas as telas do projeto (de todos os canvases), tela principal primeiro."""
    await _get_project_for_user(project_id, current_user, db)
    result = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id == project_id)
        .order_by(Screen.is_entry.desc(), Screen.created_at.asc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 200))
    )
    return result.scalars().all()


@router.post("/{project_id}/screens", response_model=ScreenOut)
async def create_project_screen(
    project_id: str,
    payload: dict,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Cria uma nova tela no primeiro canvas do projeto."""
    await _get_project_for_user(project_id, current_user, db, action="edit")
    canvas_res = await db.execute(
        select(Canvas)
        .where(Canvas.project_id == project_id)
        .order_by(Canvas.sort_order.asc(), Canvas.created_at.asc())
        .limit(1)
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
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Duplica um projeto inteiro incluindo canvases, telas e design tokens."""
    orig_proj = await _get_project_for_user(project_id, current_user, db)

    new_slug = f"{orig_proj.slug}-copia-{secrets.token_hex(2)}"
    new_proj = Project(
        name=f"{orig_proj.name} (Cópia)",
        slug=new_slug,
        description=orig_proj.description,
        workspace_id=orig_proj.workspace_id,
        owner_id=current_user.id,
        visibility=orig_proj.visibility,
        design_dials=orig_proj.design_dials
        or {"variance": 7, "motion": 4, "density": 4},
    )
    db.add(new_proj)
    await db.flush()

    # Membro proprietário do novo projeto
    pm = ProjectMember(project_id=new_proj.id, user_id=current_user.id, role="owner")
    db.add(pm)

    # Copia Tokens
    tokens_res = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == orig_proj.id)
    )
    orig_tokens = tokens_res.scalars().first()
    if orig_tokens:
        new_tokens = DesignTokens(
            project_id=new_proj.id,
            light_tokens=orig_tokens.light_tokens,
            dark_tokens=orig_tokens.dark_tokens,
            shared_tokens=orig_tokens.shared_tokens or {},
        )
        db.add(new_tokens)

    # Copia Canvases e Telas
    canvas_map = {}
    canvases_res = await db.execute(
        select(Canvas).where(Canvas.project_id == orig_proj.id)
    )
    for c in canvases_res.scalars().all():
        new_canvas = Canvas(
            project_id=new_proj.id, name=c.name, sort_order=c.sort_order
        )
        db.add(new_canvas)
        await db.flush()
        canvas_map[c.id] = new_canvas.id

        # Copia cenários de dados deste canvas
        scenarios_res = await db.execute(
            select(DataScenario).where(DataScenario.canvas_id == c.id)
        )
        for sc in scenarios_res.scalars().all():
            new_sc = DataScenario(
                canvas_id=new_canvas.id, name=sc.name, mock_data=sc.mock_data
            )
            db.add(new_sc)

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
                current_revision=1,
            )
            db.add(new_screen)
            await db.flush()

            # Cria revisão inicial no novo projeto
            new_rev = ScreenRevision(
                screen_id=new_screen.id,
                revision_number=1,
                html_content=new_screen.html_content,
                css_content=new_screen.css_content,
                js_content=new_screen.js_content,
                change_summary="Duplicação de projeto",
                actor=current_user.name,
            )
            db.add(new_rev)

            if s.is_entry:
                new_proj.entry_screen_id = new_screen.id

    await db.commit()
    await db.refresh(new_proj)
    return new_proj


@router.get("/{project_id}/export/bundle")
async def export_project_bundle(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dev Mode: Retorna mapa consolidado de todas as telas, tokens e templates do projeto."""
    project = await _get_project_for_user(project_id, current_user, db)

    # Tokens
    t_query = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == project_id)
    )
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
        bundle_screens.append(
            {
                "id": s.id,
                "name": s.name,
                "is_entry": s.is_entry,
                "html": s.html_content,
                "css": s.css_content,
                "react_component": html_to_jsx(s.html_content, s.name),
            }
        )

    return {
        "project": {"id": project.id, "name": project.name, "slug": project.slug},
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
        },
        "screens": bundle_screens,
    }


@router.get("/{project_id}/export/design")
async def export_design_corpus(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exporta o projeto no layout `design/` do Mockbird v1 (reimportável)."""
    project = await _get_project_for_user(project_id, current_user, db)

    tokens_res = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == project_id)
    )
    tokens = tokens_res.scalars().first()

    canvases_res = await db.execute(
        select(Canvas)
        .where(Canvas.project_id == project_id)
        .order_by(Canvas.sort_order.asc(), Canvas.created_at.asc())
    )

    payload_canvases = []
    for canvas in canvases_res.scalars().all():
        screens_res = await db.execute(
            select(Screen)
            .where(Screen.canvas_id == canvas.id)
            .order_by(Screen.is_entry.desc(), Screen.created_at.asc())
        )
        payload_canvases.append(
            {
                "name": canvas.name,
                "screens": [
                    {
                        "name": s.name,
                        "html_content": s.html_content,
                        "css_content": s.css_content,
                        "js_content": s.js_content,
                        "width": s.width,
                        "height": s.height,
                        "device_type": s.device_type,
                    }
                    for s in screens_res.scalars().all()
                ],
            }
        )

    blob = build_design_corpus(
        project.name,
        {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
        },
        payload_canvases,
    )
    filename = f"design-{project.slug or 'projeto'}.zip"
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Cenários de Dados Mock (DataScenario)
# ---------------------------------------------------------------------------


class ScenarioPayload(BaseModel):
    name: str
    data: Optional[Dict[str, Any]] = None
    mock_data: Optional[Dict[str, Any]] = None


@router.get("/{project_id}/scenarios")
async def list_project_scenarios(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista cenários de mock do projeto ou inicializa com 3 padrões."""
    await _get_project_for_user(project_id, current_user, db)
    c_res = await db.execute(
        select(Canvas)
        .where(Canvas.project_id == project_id)
        .order_by(Canvas.sort_order.asc(), Canvas.created_at.asc())
        .limit(1)
    )
    canvas = c_res.scalars().first()
    if not canvas:
        canvas = Canvas(project_id=project_id, name="Principal")
        db.add(canvas)
        await db.flush()

    sc_res = await db.execute(
        select(DataScenario)
        .where(DataScenario.canvas_id == canvas.id)
        .order_by(DataScenario.created_at.asc())
    )
    scenarios = sc_res.scalars().all()

    if not scenarios:
        defaults = [
            (
                "Cenário Sucesso",
                {
                    "status": "sucesso",
                    "usuario": {
                        "nome": "Maria Silva",
                        "email": "maria@empresa.com",
                        "cargo": "Administrador",
                    },
                    "metricas": {
                        "faturamento": "R$ 48.750",
                        "crescimento": "+18.4%",
                        "clientes": "142",
                    },
                    "itens": [
                        {
                            "id": 1,
                            "nome": "Item Exemplo A",
                            "status": "Ativo",
                            "valor": "R$ 1.250",
                        },
                        {
                            "id": 2,
                            "nome": "Item Exemplo B",
                            "status": "Pendente",
                            "valor": "R$ 840",
                        },
                    ],
                },
            ),
            (
                "Cenário Vazio",
                {
                    "status": "vazio",
                    "usuario": {
                        "nome": "Maria Silva",
                        "email": "maria@empresa.com",
                        "cargo": "Administrador",
                    },
                    "metricas": {
                        "faturamento": "R$ 0",
                        "crescimento": "0%",
                        "clientes": "0",
                    },
                    "itens": [],
                },
            ),
            (
                "Cenário Erro",
                {
                    "status": "erro",
                    "mensagem": "Falha na sincronização dos dados com a API remota.",
                    "itens": [],
                },
            ),
        ]
        created = []
        for name, data in defaults:
            sc = DataScenario(canvas_id=canvas.id, name=name, mock_data=data)
            db.add(sc)
            created.append(sc)
        await db.commit()
        for sc in created:
            await db.refresh(sc)
        scenarios = created

    return [
        {"id": sc.id, "name": sc.name, "data": sc.mock_data, "mock_data": sc.mock_data}
        for sc in scenarios
    ]


@router.post("/{project_id}/scenarios")
async def create_project_scenario(
    project_id: str,
    payload: ScenarioPayload,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Cria um novo cenário de dados no canvas principal do projeto."""
    await _get_project_for_user(project_id, current_user, db, action="edit")
    c_res = await db.execute(
        select(Canvas)
        .where(Canvas.project_id == project_id)
        .order_by(Canvas.sort_order.asc(), Canvas.created_at.asc())
        .limit(1)
    )
    canvas = c_res.scalars().first()
    if not canvas:
        canvas = Canvas(project_id=project_id, name="Principal")
        db.add(canvas)
        await db.flush()

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Nome do cenário é obrigatório")

    content_data = (
        payload.data if payload.data is not None else (payload.mock_data or {})
    )
    scenario = DataScenario(canvas_id=canvas.id, name=name, mock_data=content_data)
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return {
        "id": scenario.id,
        "name": scenario.name,
        "data": scenario.mock_data,
        "mock_data": scenario.mock_data,
    }


@router.delete("/{project_id}/scenarios/{scenario_id}")
async def delete_project_scenario(
    project_id: str,
    scenario_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Exclui um cenário de dados do projeto."""
    await _get_project_for_user(project_id, current_user, db, action="edit")
    sc_res = await db.execute(
        select(DataScenario)
        .join(Canvas, Canvas.id == DataScenario.canvas_id)
        .where(DataScenario.id == scenario_id, Canvas.project_id == project_id)
    )
    scenario = sc_res.scalars().first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Cenário não encontrado")

    await db.delete(scenario)
    await db.commit()
    return {"message": "Cenário excluído com sucesso"}
