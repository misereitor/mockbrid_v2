from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.timeutils import utcnow
from app.models import User, Comment, Screen
from app.routes_auth import get_current_user, require_commenter

from app.authz import authorize_screen

router = APIRouter(prefix="/api/comments", tags=["comments"])


async def _validate_screen_ownership(screen_id: str, current_user: User, db: AsyncSession, action: str = "read") -> Screen:
    return await authorize_screen(screen_id, current_user, action, db)


class CommentCreate(BaseModel):
    screen_id: str
    element_mb_id: str
    element_snippet: Optional[str] = ""
    pin_x: float
    pin_y: float
    body: str


class CommentOut(BaseModel):
    id: str
    screen_id: str
    author_name: str
    element_mb_id: str
    element_snippet: str
    pin_x: float
    pin_y: float
    body: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/screen/{screen_id}", response_model=List[CommentOut])
async def list_comments_by_screen(
    screen_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await _validate_screen_ownership(screen_id, current_user, db)
    query = await db.execute(
        select(Comment).where(Comment.screen_id == screen_id).order_by(Comment.created_at.asc())
    )
    return query.scalars().all()


@router.post("", response_model=CommentOut)
async def create_comment(
    payload: CommentCreate,
    current_user: User = Depends(require_commenter),
    db: AsyncSession = Depends(get_db)
):
    await _validate_screen_ownership(payload.screen_id, current_user, db, action="comment")
    comment = Comment(
        screen_id=payload.screen_id,
        author_id=current_user.id,
        author_name=current_user.name,
        element_mb_id=payload.element_mb_id,
        element_snippet=payload.element_snippet or "",
        pin_x=payload.pin_x,
        pin_y=payload.pin_y,
        body=payload.body,
        status="open",
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


@router.patch("/{comment_id}/resolve", response_model=CommentOut)
async def resolve_comment(
    comment_id: str,
    current_user: User = Depends(require_commenter),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")
    await _validate_screen_ownership(comment.screen_id, current_user, db, action="comment")
    if comment.author_id != current_user.id and current_user.role not in ["editor", "admin", "owner"]:
        raise HTTPException(status_code=403, detail="Apenas o autor ou editores podem resolver este comentário")
    comment.status = "resolved"
    comment.resolved_at = utcnow()
    await db.commit()
    await db.refresh(comment)
    return comment

