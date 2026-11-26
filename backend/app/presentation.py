"""Montagem do payload da apresentação (player).

Reutilizado pela rota pública (`/api/public/p/<slug>`, via share link) e pela
pré-visualização privada (`/api/projects/<id>/presentation`, só para quem tem
acesso de leitura ao projeto).
"""

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Canvas, DataScenario, DesignTokens, Project, Screen


class NoScreenError(Exception):
    """O projeto não tem nenhuma tela para apresentar."""


async def build_presentation_payload(
    project: Project,
    db: AsyncSession,
    *,
    allow_comments: bool = False,
) -> Dict[str, Any]:
    tokens_res = await db.execute(select(DesignTokens).where(DesignTokens.project_id == project.id))
    tokens = tokens_res.scalars().first()

    # Tela Principal (Entry Screen), com fallback para a primeira tela encontrada.
    screen = None
    if project.entry_screen_id:
        res = await db.execute(select(Screen).where(Screen.id == project.entry_screen_id))
        screen = res.scalars().first()

    if not screen:
        canvas_res = await db.execute(select(Canvas).where(Canvas.project_id == project.id).limit(1))
        canvas = canvas_res.scalars().first()
        if canvas:
            res = await db.execute(select(Screen).where(Screen.canvas_id == canvas.id).limit(1))
            screen = res.scalars().first()

    if not screen:
        raise NoScreenError()

    # Todas as telas, para a navegação interativa completa do protótipo.
    screens_res = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id == project.id)
        .order_by(Screen.is_entry.desc(), Screen.created_at.asc())
    )
    screens_data = [
        {
            "id": s.id,
            "name": s.name,
            "is_main": s.is_entry,
            "html_content": s.html_content,
            "css_content": s.css_content,
            "js_content": s.js_content,
            "width": s.width,
            "height": s.height,
        }
        for s in screens_res.scalars().all()
    ]

    scenarios_res = await db.execute(
        select(DataScenario)
        .join(Canvas, Canvas.id == DataScenario.canvas_id)
        .where(Canvas.project_id == project.id)
        .order_by(DataScenario.created_at.asc())
    )
    scenarios_data = [
        {"id": sc.id, "name": sc.name, "data": sc.mock_data}
        for sc in scenarios_res.scalars().all()
    ]

    return {
        "project_name": project.name,
        "slug": project.slug,
        "allow_comments": allow_comments,
        "screen": {
            "name": screen.name,
            "html_content": screen.html_content,
            "css_content": screen.css_content,
            "width": screen.width,
            "height": screen.height,
        },
        "screens": screens_data,
        "scenarios": scenarios_data,
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
            "shared": tokens.shared_tokens if tokens else {},
        },
    }
