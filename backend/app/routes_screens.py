from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.database import get_db
from app.models import User, Screen, Canvas, Project, Workspace, ScreenRevision
from app.schemas import (
    ScreenCreate,
    ScreenUpdate,
    ScreenOut,
    ScreenRevisionOut,
    BatchScreensUpdateRequest,
)
from app.routes_auth import get_current_user, require_editor
from app.authz import authorize_screen, authorize_project
from app.jsx import html_to_jsx
from app.ws import broadcaster

router = APIRouter(prefix="/api/screens", tags=["screens"])


async def _owned_canvas(canvas_id: str, current_user: User, db: AsyncSession, action: str = "read") -> Canvas:
    res = await db.execute(
        select(Canvas, Project)
        .join(Project, Project.id == Canvas.project_id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(Canvas.id == canvas_id, Workspace.organization_id == current_user.organization_id)
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    canvas, project = row[0], row[1]
    await authorize_project(project.id, current_user, action, db)
    return canvas


async def _owned_screen(screen_id: str, current_user: User, db: AsyncSession, action: str = "read") -> Screen:
    return await authorize_screen(screen_id, current_user, action, db)


@router.get("/canvas/{canvas_id}", response_model=List[ScreenOut])
async def list_screens_by_canvas(
    canvas_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await _owned_canvas(canvas_id, current_user, db, action="read")
    query = await db.execute(select(Screen).where(Screen.canvas_id == canvas_id).order_by(Screen.created_at.asc()))
    return query.scalars().all()


@router.get("/{screen_id}", response_model=ScreenOut)
async def get_screen(
    screen_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await _owned_screen(screen_id, current_user, db, action="read")


@router.post("", response_model=ScreenOut)
async def create_screen(
    payload: ScreenCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    await _owned_canvas(payload.canvas_id, current_user, db, action="edit")
    screen = Screen(
        canvas_id=payload.canvas_id,
        name=payload.name,
        is_entry=payload.is_entry or False,
        screen_kind=payload.screen_kind or "page",
        device_type=payload.device_type or "desktop",
        width=payload.width or 1440,
        height=payload.height or 900,
        html_content=payload.html_content or "",
        css_content=payload.css_content or "",
        js_content=payload.js_content or "",
    )
    db.add(screen)
    await db.commit()
    await db.refresh(screen)
    return screen


@router.put("/{screen_id}", response_model=ScreenOut)
@router.patch("/{screen_id}", response_model=ScreenOut)
async def update_screen(
    screen_id: str,
    payload: ScreenUpdate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    screen = await _owned_screen(screen_id, current_user, db, action="edit")

    update_data = payload.model_dump(exclude_unset=True)
    
    # Se marcou como is_entry, desmarca outras do mesmo canvas
    if update_data.get("is_entry") is True:
        other_screens = await db.execute(select(Screen).where(Screen.canvas_id == screen.canvas_id, Screen.id != screen.id))
        for s in other_screens.scalars().all():
            s.is_entry = False

    for key, value in update_data.items():
        setattr(screen, key, value)

    screen.current_revision += 1

    # Cria snapshot de revisão
    rev = ScreenRevision(
        screen_id=screen.id,
        revision_number=screen.current_revision,
        html_content=screen.html_content,
        css_content=screen.css_content,
        js_content=screen.js_content,
        actor=current_user.name,
        change_summary="Atualização visual/código",
    )
    db.add(rev)

    await db.commit()
    await db.refresh(screen)

    # Colaboração em tempo real: os demais editores aplicam o novo conteúdo.
    canvas_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = canvas_res.scalars().first()
    if canvas:
        await broadcaster.broadcast(
            canvas.project_id,
            {
                "type": "screen_updated",
                "screen_id": screen.id,
                "origin": current_user.id,
                "name": screen.name,
                "current_revision": screen.current_revision,
                "html_content": screen.html_content,
                "css_content": screen.css_content,
                "js_content": screen.js_content,
            },
        )
    return screen


@router.delete("/{screen_id}")
async def delete_screen(
    screen_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Exclui uma tela do projeto."""
    screen = await _owned_screen(screen_id, current_user, db, action="edit")
    await db.delete(screen)
    await db.commit()
    return {"message": "Tela excluída com sucesso", "screen_id": screen_id}


@router.get("/{screen_id}/revisions", response_model=List[ScreenRevisionOut])
async def list_screen_revisions(
    screen_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lista o histórico de revisões da tela para auditoria e reversão."""
    await _owned_screen(screen_id, current_user, db, action="read")
    res = await db.execute(
        select(ScreenRevision)
        .where(ScreenRevision.screen_id == screen_id)
        .order_by(ScreenRevision.revision_number.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 200))
    )
    return res.scalars().all()


@router.post("/{screen_id}/revisions/{revision_id}/revert", response_model=ScreenOut)
async def revert_screen_revision(
    screen_id: str,
    revision_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Reverte o código da tela para uma revisão histórica específica."""
    screen = await _owned_screen(screen_id, current_user, db, action="edit")
    rev_res = await db.execute(
        select(ScreenRevision).where(
            ScreenRevision.id == revision_id,
            ScreenRevision.screen_id == screen.id
        )
    )
    rev = rev_res.scalars().first()
    if not rev:
        raise HTTPException(status_code=404, detail="Revisão não encontrada")

    screen.html_content = rev.html_content
    screen.css_content = rev.css_content
    screen.js_content = rev.js_content
    screen.current_revision += 1

    # Cria snapshot da reversão
    new_rev = ScreenRevision(
        screen_id=screen.id,
        revision_number=screen.current_revision,
        html_content=screen.html_content,
        css_content=screen.css_content,
        js_content=screen.js_content,
        actor=current_user.name,
        change_summary=f"Reversão para revisão #{rev.revision_number}",
    )
    db.add(new_rev)
    await db.commit()
    await db.refresh(screen)
    return screen


@router.post("/{screen_id}/duplicate", response_model=ScreenOut)
async def duplicate_screen(
    screen_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Duplica uma tela inteira no mesmo canvas."""
    original = await _owned_screen(screen_id, current_user, db, action="edit")
    new_screen = Screen(
        canvas_id=original.canvas_id,
        name=f"{original.name} (Cópia)",
        is_entry=False,
        screen_kind=original.screen_kind,
        device_type=original.device_type,
        width=original.width,
        height=original.height,
        pos_x=original.pos_x + 60,
        pos_y=original.pos_y + 60,
        html_content=original.html_content,
        css_content=original.css_content,
        js_content=original.js_content,
        transition=original.transition,
        current_revision=1,
    )
    db.add(new_screen)
    await db.commit()
    await db.refresh(new_screen)

    # Cria revisão inicial da cópia
    rev = ScreenRevision(
        screen_id=new_screen.id,
        revision_number=1,
        html_content=new_screen.html_content,
        css_content=new_screen.css_content,
        js_content=new_screen.js_content,
        actor=current_user.name,
        change_summary="Duplicação da tela",
    )
    db.add(rev)
    await db.commit()
    return new_screen


@router.get("/{screen_id}/export")
async def export_screen_bundle(
    screen_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Dev Mode / Handoff: Retorna o pacote de código pronto para desenvolvimento."""
    screen = await _owned_screen(screen_id, current_user, db)
    return {
        "screen_id": screen.id,
        "name": screen.name,
        "html": screen.html_content,
        "css": screen.css_content,
        "js": screen.js_content,
        "react_jsx": html_to_jsx(screen.html_content, screen.name),
    }


@router.put("/project/{project_id}/batch")
@router.post("/project/{project_id}/batch")
async def batch_update_screens(
    project_id: str,
    payload: BatchScreensUpdateRequest,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Atualiza ou cria múltiplas telas em lote para um projeto existente."""
    project = await authorize_project(project_id, current_user, "edit", db)

    # Carrega todos os canvases do projeto
    c_res = await db.execute(
        select(Canvas).where(Canvas.project_id == project.id).order_by(Canvas.sort_order.asc())
    )
    canvases = c_res.scalars().all()
    if not canvases:
        default_canvas = Canvas(project_id=project.id, name="Principal", sort_order=0)
        db.add(default_canvas)
        await db.flush()
        canvases = [default_canvas]

    canvas_map = {c.name.lower().strip(): c for c in canvases}
    first_canvas = canvases[0]

    # Carrega todas as telas do projeto
    canvas_ids = [c.id for c in canvases]
    s_res = await db.execute(
        select(Screen).where(Screen.canvas_id.in_(canvas_ids))
    )
    existing_screens = s_res.scalars().all()
    screens_by_id = {s.id: s for s in existing_screens}
    screens_by_name = {s.name.lower().strip(): s for s in existing_screens}

    updated = []
    created = []

    for item in payload.screens:
        target_screen = None
        if item.screen_id and item.screen_id in screens_by_id:
            target_screen = screens_by_id[item.screen_id]
        elif item.screen_name:
            target_screen = screens_by_name.get(item.screen_name.lower().strip())

        if target_screen:
            target_screen.html_content = item.html_content
            if item.css_content is not None:
                target_screen.css_content = item.css_content
            if item.js_content is not None:
                target_screen.js_content = item.js_content
            if item.viewport:
                dtype = "mobile" if item.viewport == "mobile" else ("tablet" if item.viewport == "tablet" else "desktop")
                target_screen.device_type = dtype
                if dtype == "mobile":
                    target_screen.width, target_screen.height = 375, 812
                elif dtype == "tablet":
                    target_screen.width, target_screen.height = 768, 1024
                else:
                    target_screen.width, target_screen.height = 1440, 900

            target_screen.current_revision += 1
            rev = ScreenRevision(
                screen_id=target_screen.id,
                revision_number=target_screen.current_revision,
                html_content=target_screen.html_content,
                css_content=target_screen.css_content or "",
                js_content=target_screen.js_content or "",
                actor=current_user.name,
                change_summary=item.change_summary or "Atualização em lote via API/MCP",
            )
            db.add(rev)
            updated.append({"id": target_screen.id, "name": target_screen.name, "canvas_id": target_screen.canvas_id})
        else:
            target_canvas = first_canvas
            if item.canvas_name and item.canvas_name.lower().strip() in canvas_map:
                target_canvas = canvas_map[item.canvas_name.lower().strip()]

            new_name = item.screen_name or f"Tela {len(existing_screens) + len(created) + 1}"
            dtype = "mobile" if (item.viewport == "mobile") else ("tablet" if item.viewport == "tablet" else "desktop")
            w = 375 if dtype == "mobile" else (768 if dtype == "tablet" else 1440)
            h = 812 if dtype == "mobile" else (1024 if dtype == "tablet" else 900)
            new_screen = Screen(
                canvas_id=target_canvas.id,
                name=new_name,
                html_content=item.html_content,
                css_content=item.css_content or "",
                js_content=item.js_content or "",
                device_type=dtype,
                width=w,
                height=h,
                current_revision=1,
            )
            db.add(new_screen)
            await db.flush()

            rev = ScreenRevision(
                screen_id=new_screen.id,
                revision_number=1,
                html_content=new_screen.html_content,
                css_content=new_screen.css_content,
                js_content=new_screen.js_content,
                actor=current_user.name,
                change_summary="Criação em lote via API/MCP",
            )
            db.add(rev)
            screens_by_id[new_screen.id] = new_screen
            screens_by_name[new_screen.name.lower().strip()] = new_screen
            created.append({"id": new_screen.id, "name": new_screen.name, "canvas_id": new_screen.canvas_id})

    await db.commit()

    # Notifica via WebSocket
    await broadcaster.broadcast(
        project.id,
        {
            "type": "screens_batch_updated",
            "project_id": project.id,
            "origin": current_user.id,
            "updated_count": len(updated),
            "created_count": len(created),
        },
    )

    return {
        "status": "success",
        "project_id": project.id,
        "total_received": len(payload.screens),
        "updated_screens": updated,
        "created_screens": created,
        "message": f"{len(updated)} telas atualizadas e {len(created)} telas criadas com sucesso.",
    }

