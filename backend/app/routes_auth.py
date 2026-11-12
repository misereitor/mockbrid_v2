from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, func
from datetime import timedelta
import logging
import secrets

from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    hash_session_token,
)
from app.auth_tokens import (
    RESET_PASSWORD,
    VERIFY_EMAIL,
    consume_auth_token,
    issue_auth_token,
)
from app.config import settings
from app.database import get_db
from app.mailer import (
    EmailDeliveryError,
    EmailNotConfigured,
    build_link,
    get_email_settings,
    provider_ready,
    send_password_reset_email,
    send_verification_email,
)
from app.models import User, Organization, Workspace, Session
from app.schemas import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserRegister,
    UserLogin,
    UserOut,
    UserProfileUpdate,
    UserPasswordChange,
    VerifyEmailRequest,
)
from app.timeutils import utcnow

logger = logging.getLogger(__name__)

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

    # Valida estritamente sessão ativa no banco (revogação real de token).
    # O banco guarda apenas o hash SHA-256 do JWT, nunca o token em claro.
    session_res = await db.execute(select(Session).where(Session.token == hash_session_token(token)))
    active_session = session_res.scalars().first()
    if not active_session or active_session.expires_at < utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão inválida, revogada ou expirada"
        )

    # Proteção CSRF para requisições autenticadas via Cookie nos métodos mutantes
    if is_cookie_auth and request.method in ["POST", "PUT", "PATCH", "DELETE"]:
        csrf_header = request.headers.get("X-CSRF-Token")
        expected_csrf = active_session.csrf_token
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


def require_role(*allowed_roles: str):
    """Fábrica de dependências para controle de acesso baseado em papéis (RBAC)."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Ação não permitida para o seu papel ({current_user.role}). Permissões necessárias: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker


require_editor = require_role("owner", "admin", "editor")
require_commenter = require_role("owner", "admin", "editor", "commenter")
require_admin = require_role("owner", "admin")


def _is_designated_admin_email(email: str) -> bool:
    configured = (settings.SYSTEM_ADMIN_EMAIL or "").strip().lower()
    return bool(configured and email.strip().lower() == configured)


async def require_system_admin(current_user: User = Depends(get_current_user)) -> User:
    """Administrador da instância (primeira conta criada)."""
    if not current_user.is_system_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador do sistema pode acessar esta área.",
        )
    return current_user


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

    # A primeira conta da instância é o administrador do sistema (configura
    # e-mail e demais ajustes globais).
    total_users = await db.scalar(select(func.count(User.id)))
    is_first_user = not total_users

    # Cria o usuário
    user = User(
        organization_id=org.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        role="owner",
        is_system_admin=is_first_user,
    )
    db.add(user)
    await db.flush()

    # Cria a sessão e token JWT
    token = create_access_token({"sub": user.id, "org_id": org.id, "role": user.role})
    csrf_token = secrets.token_hex(16)

    session = Session(
        user_id=user.id,
        token=hash_session_token(token),
        csrf_token=csrf_token,
        expires_at=utcnow() + timedelta(days=7),
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)

    if _is_designated_admin_email(user.email) and not user.is_system_admin:
        user.is_system_admin = True
        await db.commit()

    # Verificação de e-mail: só envia quando o admin ativou a exigência e o
    # transporte está pronto. Falha de e-mail nunca derruba o cadastro.
    try:
        email_settings = await get_email_settings(db)
        if email_settings.require_verification and provider_ready(email_settings):
            raw_token = await issue_auth_token(db, user.id, VERIFY_EMAIL)
            await db.commit()
            await send_verification_email(
                db, user, build_link(email_settings, f"/verify-email?token={raw_token}")
            )
    except (EmailNotConfigured, EmailDeliveryError) as exc:
        logger.warning("Cadastro %s: verificação não enviada (%s)", user.email, exc)
    except Exception:
        logger.exception("Cadastro %s: falha inesperada ao enviar verificação", user.email)

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

    if _is_designated_admin_email(user.email) and not user.is_system_admin:
        user.is_system_admin = True

    token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role})
    csrf_token = secrets.token_hex(16)

    session = Session(
        user_id=user.id,
        token=hash_session_token(token),
        csrf_token=csrf_token,
        expires_at=utcnow() + timedelta(days=7),
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
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Encerra apenas a sessão atual (os outros dispositivos seguem logados)."""
    token = request.cookies.get("mockbird_token")
    if not token:
        auth_header = request.headers.get("Authorization") or ""
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if token:
        await db.execute(
            delete(Session).where(
                Session.user_id == current_user.id,
                Session.token == hash_session_token(token),
            )
        )
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


@router.get("/email-status")
async def email_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Informa à UI se o envio está configurado e se há verificação pendente."""
    row = await get_email_settings(db)
    return {
        "configured": provider_ready(row),
        "require_verification": row.require_verification,
        "email_verified": current_user.email_verified,
    }


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Envia link de redefinição. Resposta é genérica para não revelar contas."""
    row = await get_email_settings(db)
    if not provider_ready(row):
        raise HTTPException(
            status_code=503,
            detail=(
                "O envio de e-mail ainda não foi configurado pelo administrador. "
                "Peça a ele para abrir Configurações → E-mail."
            ),
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalars().first()

    if user and user.is_active:
        raw_token = await issue_auth_token(db, user.id, RESET_PASSWORD)
        await db.commit()
        try:
            await send_password_reset_email(
                db, user, build_link(row, f"/reset-password?token={raw_token}")
            )
        except EmailNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except EmailDeliveryError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Não foi possível enviar o e-mail agora: {exc}",
            ) from exc

    return {
        "status": "sent",
        "message": "Se este e-mail estiver cadastrado, enviaremos as instruções em instantes.",
    }


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    token = await consume_auth_token(db, payload.token, RESET_PASSWORD)
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Link inválido ou expirado. Solicite uma nova redefinição.",
        )

    user = await db.get(User, token.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Conta indisponível.")

    user.password_hash = hash_password(payload.new_password)
    # Receber o link no endereço prova a posse da caixa de entrada.
    user.email_verified = True
    user.email_verified_at = utcnow()
    token.used_at = utcnow()
    # Toda sessão antiga cai: o link de e-mail não deve manter dispositivos logados.
    await db.execute(delete(Session).where(Session.user_id == user.id))
    await db.commit()
    return {"status": "success", "message": "Senha redefinida. Entre com a nova senha."}


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    token = await consume_auth_token(db, payload.token, VERIFY_EMAIL)
    if not token:
        raise HTTPException(status_code=400, detail="Link inválido ou expirado.")

    user = await db.get(User, token.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Conta não encontrada.")

    user.email_verified = True
    user.email_verified_at = utcnow()
    token.used_at = utcnow()
    await db.commit()
    return {"status": "success", "message": "E-mail confirmado com sucesso."}


@router.post("/resend-verification")
async def resend_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.email_verified:
        return {"status": "already_verified"}

    row = await get_email_settings(db)
    if not provider_ready(row):
        raise HTTPException(
            status_code=503,
            detail="O envio de e-mail ainda não foi configurado pelo administrador.",
        )

    raw_token = await issue_auth_token(db, current_user.id, VERIFY_EMAIL)
    await db.commit()
    try:
        await send_verification_email(
            db, current_user, build_link(row, f"/verify-email?token={raw_token}")
        )
    except EmailNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "sent", "to": current_user.email}


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

