from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth import verify_password
from app.database import get_db
from app.models import Project, Screen, DesignTokens, Canvas, ShareLink, Comment, DataScenario
from app.timeutils import utcnow

router = APIRouter(prefix="/api/public", tags=["public"])


async def _resolve_project(slug: str, password: Optional[str], db: AsyncSession):
    """Resolve o slug para um projeto, exigindo share link válido ou publicação explícita."""
    link_res = await db.execute(select(ShareLink).where(ShareLink.slug == slug))
    link = link_res.scalars().first()

    if link:
        if link.expires_at and link.expires_at < utcnow():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Este link de apresentação expirou")

        if link.password_hash:
            if not password:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Este link exige senha. Informe ?password=...",
                )
            if not verify_password(password, link.password_hash):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Senha incorreta")

        project_res = await db.execute(
            select(Project).where(Project.id == link.project_id, Project.is_archived == False)  # noqa: E712
        )
        project = project_res.scalars().first()
        if not project:
            raise HTTPException(status_code=404, detail="Apresentação não encontrada")
        return project, link

    # Sem share link: só projetos explicitamente publicados são públicos.
    project_res = await db.execute(
        select(Project).where(
            Project.slug == slug,
            Project.is_archived == False,  # noqa: E712
            Project.is_published == True,  # noqa: E712
        )
    )
    project = project_res.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Apresentação não encontrada ou privada")
    return project, None


@router.get("/p/{slug}")
async def get_public_presentation(
    slug: str,
    password: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    project, link = await _resolve_project(slug, password, db)

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

    # Busca todas as telas para navegação completa interativa do protótipo
    screens_res = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id == project.id)
        .order_by(Screen.is_entry.desc(), Screen.created_at.asc())
    )
    all_screens = screens_res.scalars().all()
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
        for s in all_screens
    ]

    # Busca todos os cenários de mock do projeto
    sc_res = await db.execute(
        select(DataScenario)
        .join(Canvas, Canvas.id == DataScenario.canvas_id)
        .where(Canvas.project_id == project.id)
        .order_by(DataScenario.created_at.asc())
    )
    scenarios_data = [
        {"id": sc.id, "name": sc.name, "data": sc.mock_data}
        for sc in sc_res.scalars().all()
    ]

    if link:
        link.view_count += 1
        await db.commit()

    return {
        "project_name": project.name,
        "slug": project.slug,
        "allow_comments": bool(link.allow_comments) if link else False,
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


# ---------------------------------------------------------------------------
# Comentários de visitantes (share links com allow_comments)
# ---------------------------------------------------------------------------

class GuestCommentCreate(BaseModel):
    screen_id: str
    element_mb_id: str = ""
    element_snippet: str = ""
    pin_x: float = 0.0
    pin_y: float = 0.0
    body: str = Field(..., min_length=1, max_length=4000)
    guest_name: Optional[str] = Field(None, max_length=80)


class GuestCommentOut(BaseModel):
    id: str
    screen_id: str
    author_name: str
    element_mb_id: str
    element_snippet: str
    pin_x: float
    pin_y: float
    body: str
    status: str
    created_at: object

    class Config:
        from_attributes = True


async def _resolve_commentable(slug: str, password: Optional[str], db: AsyncSession):
    project, link = await _resolve_project(slug, password, db)
    if not link or not link.allow_comments:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este link não permite comentários",
        )
    return project, link


async def _screen_in_project(project_id: str, screen_id: str, db: AsyncSession) -> Screen:
    res = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Screen.id == screen_id, Canvas.project_id == project_id)
    )
    screen = res.scalars().first()
    if not screen:
        raise HTTPException(status_code=404, detail="Tela não encontrada neste projeto")
    return screen


@router.get("/p/{slug}/comments", response_model=List[GuestCommentOut])
async def list_public_comments(
    slug: str,
    screen_id: Optional[str] = None,
    password: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    project, _link = await _resolve_commentable(slug, password, db)
    query = (
        select(Comment)
        .join(Screen, Screen.id == Comment.screen_id)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id == project.id)
    )
    if screen_id:
        await _screen_in_project(project.id, screen_id, db)
        query = query.where(Comment.screen_id == screen_id)
    res = await db.execute(query.order_by(Comment.created_at.asc()))
    return res.scalars().all()


@router.post("/p/{slug}/comments", response_model=GuestCommentOut)
async def create_public_comment(
    slug: str,
    payload: GuestCommentCreate,
    password: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    project, _link = await _resolve_commentable(slug, password, db)
    await _screen_in_project(project.id, payload.screen_id, db)

    author_name = (payload.guest_name or "").strip() or "Visitante"
    comment = Comment(
        screen_id=payload.screen_id,
        author_id=None,
        author_name=author_name,
        element_mb_id=payload.element_mb_id,
        element_snippet=payload.element_snippet[:2000],
        pin_x=payload.pin_x,
        pin_y=payload.pin_y,
        body=payload.body.strip(),
        status="open",
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    from app.ws import broadcaster

    await broadcaster.broadcast(
        project.id,
        {
            "type": "comment_created",
            "comment": {
                "id": comment.id,
                "screen_id": comment.screen_id,
                "author_name": comment.author_name,
                "body": comment.body,
                "pin_x": comment.pin_x,
                "pin_y": comment.pin_y,
                "element_mb_id": comment.element_mb_id,
            },
        },
    )
    return comment
