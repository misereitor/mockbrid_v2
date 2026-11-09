from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.database import get_db
from app.models import User, Screen, Canvas, Project, Workspace, ScreenRevision
from app.schemas import ScreenCreate, ScreenUpdate, ScreenOut
from app.routes_auth import get_current_user

router = APIRouter(prefix="/api/screens", tags=["screens"])


async def _owned_canvas(canvas_id: str, current_user: User, db: AsyncSession) -> Canvas:
    """Canvas só é acessível se o projeto pertence à organização do usuário."""
    res = await db.execute(
        select(Canvas)
        .join(Project, Project.id == Canvas.project_id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(Canvas.id == canvas_id, Workspace.organization_id == current_user.organization_id)
    )
    canvas = res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    return canvas


async def _owned_screen(screen_id: str, current_user: User, db: AsyncSession) -> Screen:
    """Tela só é acessível se pertence à organização do usuário (evita IDOR entre tenants)."""
    res = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .join(Project, Project.id == Canvas.project_id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(Screen.id == screen_id, Workspace.organization_id == current_user.organization_id)
    )
    screen = res.scalars().first()
    if not screen:
        raise HTTPException(status_code=404, detail="Tela não encontrada")
    return screen


@router.get("/canvas/{canvas_id}", response_model=List[ScreenOut])
async def list_screens_by_canvas(
    canvas_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await _owned_canvas(canvas_id, current_user, db)
    query = await db.execute(select(Screen).where(Screen.canvas_id == canvas_id).order_by(Screen.created_at.asc()))
    return query.scalars().all()


@router.get("/{screen_id}", response_model=ScreenOut)
async def get_screen(
    screen_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await _owned_screen(screen_id, current_user, db)


@router.post("", response_model=ScreenOut)
async def create_screen(
    payload: ScreenCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await _owned_canvas(payload.canvas_id, current_user, db)
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    screen = await _owned_screen(screen_id, current_user, db)

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
    return screen


@router.delete("/{screen_id}")
async def delete_screen(
    screen_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Exclui uma tela do projeto."""
    screen = await _owned_screen(screen_id, current_user, db)
    await db.delete(screen)
    await db.commit()
    return {"message": "Tela excluída com sucesso", "screen_id": screen_id}

