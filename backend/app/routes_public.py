from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models import Project, Screen, DesignTokens, Canvas

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/p/{slug}")
async def get_public_presentation(
    slug: str,
    db: AsyncSession = Depends(get_db)
):
    # Busca projeto pelo slug público
    p_query = await db.execute(select(Project).where(Project.slug == slug, Project.is_archived == False))
    project = p_query.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Apresentação não encontrada ou privada")

    # Tokens
    t_query = await db.execute(select(DesignTokens).where(DesignTokens.project_id == project.id))
    tokens = t_query.scalars().first()

    # Busca a Tela Principal (Entry Screen)
    screen = None
    if project.entry_screen_id:
        s_query = await db.execute(select(Screen).where(Screen.id == project.entry_screen_id))
        screen = s_query.scalars().first()

    if not screen:
        # Fallback: primeira tela encontrada
        c_query = await db.execute(select(Canvas).where(Canvas.project_id == project.id).limit(1))
        canvas = c_query.scalars().first()
        if canvas:
            s_query = await db.execute(select(Screen).where(Screen.canvas_id == canvas.id).limit(1))
            screen = s_query.scalars().first()

    if not screen:
        raise HTTPException(status_code=404, detail="Nenhuma tela configurada para este projeto")

    return {
        "project_name": project.name,
        "slug": project.slug,
        "screen": {
            "name": screen.name,
            "html_content": screen.html_content,
            "css_content": screen.css_content,
            "width": screen.width,
            "height": screen.height,
        },
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
            "shared": tokens.shared_tokens if tokens else {},
        }
    }

