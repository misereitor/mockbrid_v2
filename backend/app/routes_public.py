from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth import verify_password
from app.authz import authorize_project
from app.database import get_db
from app.models import Project, Screen, Canvas, ShareLink, Comment
from app.optional_auth import get_optional_user
from app.presentation import NoScreenError, build_presentation_payload
from app.timeutils import utcnow

router = APIRouter(prefix="/api/public", tags=["public"])


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    """Erro com código estável para o frontend não depender do texto."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": detail})


async def _resolve_project(
    slug: str,
    password: Optional[str],
    request: Request,
    db: AsyncSession,
):
    """Resolve o token do share link para um projeto, aplicando as permissões do link.

    Só share links abrem a apresentação pública. O slug do projeto NÃO resolve mais:
    ele é curto e adivinhável, e a publicação permanente foi descontinuada.
    """
    link_res = await db.execute(select(ShareLink).where(ShareLink.slug == slug))
    link = link_res.scalars().first()
    if not link:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "Apresentação não encontrada")

    if link.expires_at and link.expires_at < utcnow():
        raise _error(status.HTTP_410_GONE, "expired", "Este link de apresentação expirou")

    project_res = await db.execute(
        select(Project).where(Project.id == link.project_id, Project.is_archived == False)  # noqa: E712
    )
    project = project_res.scalars().first()
    if not project:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "Apresentação não encontrada")

    if (link.access_mode or "anyone") == "org":
        user = await get_optional_user(request, db)
        if not user:
            raise _error(
                status.HTTP_401_UNAUTHORIZED,
                "login_required",
                "Este link é restrito à organização. Entre para visualizar.",
            )
        try:
            await authorize_project(project.id, user, "read", db)
        except HTTPException:
            # 404 (não 403): não confirma a existência do projeto a quem não tem acesso.
            raise _error(status.HTTP_404_NOT_FOUND, "not_found", "Apresentação não encontrada")

    if link.password_hash:
        if not password:
            raise _error(
                status.HTTP_401_UNAUTHORIZED,
                "password_required",
                "Este link exige senha.",
            )
        if not verify_password(password, link.password_hash):
            raise _error(status.HTTP_403_FORBIDDEN, "password_invalid", "Senha incorreta")

    return project, link


@router.get("/p/{slug}")
async def get_public_presentation(
    slug: str,
    request: Request,
    x_share_password: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    # A senha viaja só no cabeçalho: na query string ela vaza em logs e no histórico.
    project, link = await _resolve_project(slug, x_share_password, request, db)

    try:
        payload = await build_presentation_payload(
            project, db, allow_comments=bool(link.allow_comments)
        )
    except NoScreenError:
        raise HTTPException(status_code=404, detail="Nenhuma tela configurada para este projeto")

    link.view_count += 1
    await db.commit()
    return payload


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


async def _resolve_commentable(
    slug: str, password: Optional[str], request: Request, db: AsyncSession
):
    project, link = await _resolve_project(slug, password, request, db)
    if not link.allow_comments:
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
    request: Request,
    screen_id: Optional[str] = None,
    x_share_password: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    project, _link = await _resolve_commentable(slug, x_share_password, request, db)
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
    request: Request,
    x_share_password: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    project, _link = await _resolve_commentable(slug, x_share_password, request, db)
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
