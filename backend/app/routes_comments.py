from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import User, Comment, Screen
from app.routes_auth import get_current_user

router = APIRouter(prefix="/api/comments", tags=["comments"])


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
    db: AsyncSession = Depends(get_db)
):
    query = await db.execute(
        select(Comment).where(Comment.screen_id == screen_id).order_by(Comment.created_at.asc())
    )
    return query.scalars().all()


@router.post("", response_model=CommentOut)
async def create_comment(
    payload: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
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
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")
    comment.status = "resolved"
    comment.resolved_at = datetime.utcnow()
    await db.commit()
    await db.refresh(comment)
    return comment

