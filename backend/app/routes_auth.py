from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from datetime import datetime, timedelta
import secrets

from app.config import settings
from app.database import get_db
from app.models import User, Organization, Workspace, Session
from app.schemas import UserRegister, UserLogin, UserOut, UserProfileUpdate, UserPasswordChange
from app.auth import hash_password, verify_password, create_access_token, decode_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    is_cookie_auth = False
    token = request.cookies.get("mockbird_token")
    if token:
        is_cookie_auth = True
    else:
        # Tenta pelo header Authorization
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")

    user_id = payload["sub"]

    # Valida sessão ativa no banco se houver
    session_res = await db.execute(select(Session).where(Session.token == token))
    active_session = session_res.scalars().first()
    if active_session and active_session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada")

    # Proteção CSRF para requisições autenticadas via Cookie nos métodos mutantes
    if is_cookie_auth and request.method in ["POST", "PUT", "PATCH", "DELETE"]:
        csrf_header = request.headers.get("X-CSRF-Token")
        expected_csrf = active_session.csrf_token if active_session else request.cookies.get("mockbird_csrf")
        if not csrf_header or not expected_csrf or not secrets.compare_digest(csrf_header, expected_csrf):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Falha de validação CSRF: token ausente ou inválido"
            )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inativo ou inexistente")

    return user


@router.post("/register", response_model=UserOut)
async def register(payload: UserRegister, response: Response, db: AsyncSession = Depends(get_db)):
    # Verifica se o e-mail já existe
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")

    # Cria a organização inicial
    org_slug = payload.organization_name.lower().replace(" ", "-") + f"-{secrets.token_hex(3)}"
    org = Organization(name=payload.organization_name, slug=org_slug)
    db.add(org)
    await db.flush()

    # Cria o Workspace padrão
    ws = Workspace(name="Geral", slug="geral", organization_id=org.id)
    db.add(ws)

    # Cria o usuário
    user = User(
        organization_id=org.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        role="owner",
    )
    db.add(user)
    await db.flush()

    # Cria a sessão e token JWT
    token = create_access_token({"sub": user.id, "org_id": org.id, "role": user.role})
    csrf_token = secrets.token_hex(16)

    session = Session(
        user_id=user.id,
        token=token,
        csrf_token=csrf_token,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)

    # Define cookies (secure=True em produção, False em homologação HTTP)
    is_prod = (settings.ENVIRONMENT == "production")
    response.set_cookie(
        key="mockbird_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=60 * 60 * 24 * 7,
    )
    response.set_cookie(
        key="mockbird_csrf",
        value=csrf_token,
        httponly=False,  # JS pode ler para anexar no header CSRF
        samesite="lax",
        secure=is_prod,
        max_age=60 * 60 * 24 * 7,
    )

    return user


@router.post("/login", response_model=UserOut)
async def login(payload: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalars().first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Credenciais inválidas")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Conta desativada")

    token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role})
    csrf_token = secrets.token_hex(16)

    session = Session(
        user_id=user.id,
        token=token,
        csrf_token=csrf_token,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(session)
    await db.commit()

    is_prod = (settings.ENVIRONMENT == "production")
    response.set_cookie(
        key="mockbird_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=60 * 60 * 24 * 7,
    )
    response.set_cookie(
        key="mockbird_csrf",
        value=csrf_token,
        httponly=False,
        samesite="lax",
        secure=is_prod,
        max_age=60 * 60 * 24 * 7,
    )

    return user


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
async def logout(response: Response, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Deleta sessões ativas do usuário
    await db.execute(delete(Session).where(Session.user_id == current_user.id))
    await db.commit()
    response.delete_cookie("mockbird_token")
    response.delete_cookie("mockbird_csrf")
    return {"message": "Sessão encerrada com sucesso"}


@router.patch("/profile", response_model=UserOut)
async def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    current_user.name = payload.name.strip()
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/change-password")
async def change_password(
    payload: UserPasswordChange,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    
    current_user.password_hash = hash_password(payload.new_password)
    # Revoga sessões antigas por segurança
    await db.execute(delete(Session).where(Session.user_id == current_user.id))
    await db.commit()
    return {"message": "Senha alterada com sucesso. Por favor faça login novamente."}

