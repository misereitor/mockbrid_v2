from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import base64
import hashlib
import json
import logging
import secrets
import re
from html.parser import HTMLParser

from app.database import get_db
from app.storage import save_asset
from app.models import (
    Canvas,
    Screen,
    DesignTokens,
    User,
    MCPApiKey,
    ScreenRevision,
    Project,
    Workspace,
    Asset,
    DataScenario,
    Comment,
)
from app.routes_auth import get_current_user, require_editor
from app.timeutils import utcnow
from app.authz import authorize_project, authorize_screen, get_effective_project_role
from app.jsx import html_to_jsx
from app.routes_assets import generate_asset_signature
from app.ws import broadcaster
from app.screen_renderer import (
    render_screen_screenshot,
    simulate_element_interaction,
    simulate_sequence_interactions,
    diagnose_screen_structure,
    audit_screen_rules,
    compare_rendered_screens,
)
from app.design_corpus import parse_design_corpus, DesignCorpusError, nest_tokens
from app.routes_projects import apply_design_corpus_to_project

router = APIRouter(tags=["mcp"])
logger = logging.getLogger(__name__)


def build_public_url(request: Optional[Request], path_with_query: str) -> str:
    """Constrói URL pública acessível absoluta para assets e screenshots retornados ao agente MCP."""
    if not request:
        return f"https://tradit.ddns.net/mockbrid{path_with_query}"
    prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    if not prefix and "/mockbrid" in request.headers.get("referer", ""):
        prefix = "/mockbrid"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "tradit.ddns.net"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    return f"{proto}://{host}{prefix}{path_with_query}"


def hash_mcp_key(raw_key: str) -> str:
    """Gera hash SHA-256 seguro da chave de API MCP para armazenamento no banco."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# ============================================================================
# Schemas Pydantic para Gestão de Chaves e Ferramentas MCP
# ============================================================================


class MCPKeyProjectOut(BaseModel):
    id: str
    name: str


class MCPKeyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    project_id: Optional[str] = None
    project_ids: Optional[List[str]] = None
    scopes: Optional[List[str]] = ["project:read", "screen:write", "export:read"]
    expires_in_days: Optional[int] = 90


class MCPKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    project_ids: Optional[List[str]] = None
    scopes: Optional[List[str]] = None


class MCPKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    project_id: Optional[str] = None
    project_ids: List[str] = []
    projects: List[MCPKeyProjectOut] = []
    project_name: Optional[str] = None
    scopes: List[str]
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime
    raw_key: Optional[str] = None

    class Config:
        from_attributes = True


class MCPListProjectsRequest(BaseModel):
    limit: Optional[int] = 50


class MCPGetScreenRequest(BaseModel):
    screen_id: str
    include_html: Optional[bool] = True
    include_css: Optional[bool] = True
    include_js: Optional[bool] = True
    include_tokens: Optional[bool] = True
    fields: Optional[List[str]] = None


class MCPRestoreScreenRevisionRequest(BaseModel):
    screen_id: str
    revision: int


class MCPRenderScreenStateRequest(BaseModel):
    screen_id: str
    actions: List[Dict[str, Any]]
    viewport: Optional[str] = "desktop"
    theme: Optional[str] = "light"
    full_page: Optional[bool] = False


class MCPDiagnoseScreenRequest(BaseModel):
    screen_id: str
    viewport: Optional[str] = "desktop"
    theme: Optional[str] = "light"


class MCPValidateScreenRequest(BaseModel):
    screen_id: str


class MCPImportProjectZipRequest(BaseModel):
    project_id: str
    zip_base64: str
    change_summary: Optional[str] = "Atualização via MCP ZIP Import"


class MCPCreateScreenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    project_id: Optional[str] = None
    canvas_id: Optional[str] = None
    html_content: Optional[str] = None
    css_content: Optional[str] = ""
    js_content: Optional[str] = ""
    width: Optional[int] = 1440
    height: Optional[int] = 900
    is_entry: Optional[bool] = False


class MCPDuplicateScreenRequest(BaseModel):
    screen_id: str
    new_name: Optional[str] = None


class MCPDeleteScreenRequest(BaseModel):
    screen_id: str


class MCPPatchRequest(BaseModel):
    screen_id: str
    element_mb_id: str
    new_html_snippet: str
    change_summary: Optional[str] = "Alteração via MCP Agent"


class MCPUpdateScreenHTMLRequest(BaseModel):
    screen_id: str
    html_content: str
    change_summary: Optional[str] = "Atualização via MCP Agent"
    css_content: Optional[str] = None
    js_content: Optional[str] = None


class MCPBatchScreenItem(BaseModel):
    screen_id: Optional[str] = None
    screen_name: Optional[str] = None
    canvas_name: Optional[str] = None
    html_content: str
    css_content: Optional[str] = None
    js_content: Optional[str] = None
    viewport: Optional[str] = None
    change_summary: Optional[str] = "Atualização em lote via MCP Agent"


class MCPBatchUpdateScreensRequest(BaseModel):
    project_id: Optional[str] = None
    screens: List[MCPBatchScreenItem]


class MCPUpdateDesignTokensRequest(BaseModel):
    project_id: str
    light_tokens: Optional[Dict[str, Any]] = None
    dark_tokens: Optional[Dict[str, Any]] = None
    shared_tokens: Optional[Dict[str, Any]] = None


class MCPListAssetsRequest(BaseModel):
    project_id: str


class MCPListScenariosRequest(BaseModel):
    project_id: str


class MCPSetScenarioRequest(BaseModel):
    project_id: str
    name: str
    mock_data: Dict[str, Any]
    scenario_id: Optional[str] = None


class MCPValidateHTMLRequest(BaseModel):
    html_content: str


class MCPRenderScreenshotRequest(BaseModel):
    screen_id: str
    viewport: Optional[str] = "desktop"
    theme: Optional[str] = "light"
    full_page: Optional[bool] = False


class MCPInteractElementRequest(BaseModel):
    screen_id: str
    element_mb_id: Optional[str] = None
    selector: Optional[str] = None
    action: Optional[str] = "click"
    input_value: Optional[str] = None
    viewport: Optional[str] = "desktop"
    theme: Optional[str] = "light"
    capture_screenshot: Optional[bool] = True


class MCPSearchScreensRequest(BaseModel):
    project_id: Optional[str] = None
    query: Optional[str] = None
    name_query: Optional[str] = None
    canvas_id: Optional[str] = None
    canvas_name: Optional[str] = None
    mb_id: Optional[str] = None
    html_query: Optional[str] = None
    device_type: Optional[str] = None
    is_entry: Optional[bool] = None
    limit: Optional[int] = 20
    offset: Optional[int] = 0
    include_snippet: Optional[bool] = True


class MCPGetDesignTokensRequest(BaseModel):
    project_id: Optional[str] = None
    theme: Optional[str] = "all"  # all, light, dark, shared
    format: Optional[str] = "json"  # json, css, dtcg, all


class MCPGetComponentLibraryRequest(BaseModel):
    project_id: Optional[str] = None
    category: Optional[str] = None
    query: Optional[str] = None
    include_html: Optional[bool] = True
    include_presets: Optional[bool] = True


class MCPCompareScreensRequest(BaseModel):
    screen_id: Optional[str] = None
    screen_id_a: Optional[str] = None
    screen_id_b: Optional[str] = None
    revision_a: Optional[int] = None
    revision_b: Optional[int] = None
    viewport: Optional[str] = "desktop"
    theme: Optional[str] = "light"
    full_page: Optional[bool] = False
    include_visual_diff: Optional[bool] = True


class MCPListScreenRevisionsRequest(BaseModel):
    screen_id: str
    limit: Optional[int] = 30


class MCPGetCanvasRequest(BaseModel):
    project_id: Optional[str] = None
    canvas_id: Optional[str] = None
    canvas_name: Optional[str] = None
    include_screens: Optional[bool] = True


class MCPUploadAssetRequest(BaseModel):
    project_id: Optional[str] = None
    filename: str
    data_base64: str
    content_type: Optional[str] = "image/png"


class MCPGetScreenCommentsRequest(BaseModel):
    screen_id: str
    status: Optional[str] = "all"  # all, open, resolved


class MCPAddCommentRequest(BaseModel):
    screen_id: str
    body: str = Field(..., min_length=1)
    element_mb_id: Optional[str] = ""
    element_snippet: Optional[str] = ""
    pin_x: Optional[float] = 50.0
    pin_y: Optional[float] = 50.0
    author_name: Optional[str] = None
    resolve_comment_id: Optional[str] = None


class MCPRenameScreenRequest(BaseModel):
    screen_id: str
    new_name: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    device_type: Optional[str] = None
    screen_kind: Optional[str] = None
    is_entry: Optional[bool] = None
    pos_x: Optional[int] = None
    pos_y: Optional[int] = None
    transition: Optional[str] = None


class MCPMoveScreenToCanvasRequest(BaseModel):
    screen_id: str
    target_canvas_id: Optional[str] = None
    target_canvas_name: Optional[str] = None
    create_if_missing: Optional[bool] = True


class MCPGetProjectSettingsRequest(BaseModel):
    project_id: Optional[str] = None
    update_name: Optional[str] = None
    update_description: Optional[str] = None
    update_design_dials: Optional[Dict[str, Any]] = None
    update_entry_screen_id: Optional[str] = None




# ============================================================================
# Analisador / Validador de HTML para Ferramenta MCP
# ============================================================================


class ScreenHTMLValidator(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: List[tuple] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.mb_ids: List[str] = []
        self.total_tags: int = 0
        self.void_tags = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }

    def handle_starttag(self, tag, attrs):
        self.total_tags += 1
        tag_lower = tag.lower()
        attrs_dict = dict(attrs)

        mb_id = attrs_dict.get("data-mb-id") or attrs_dict.get("id")
        if mb_id:
            if mb_id in self.mb_ids:
                self.warnings.append(f"Identificador duplicado encontrado: '{mb_id}'")
            else:
                self.mb_ids.append(mb_id)

        if tag_lower == "script":
            self.warnings.append("Tag <script> inline detectada. Prefira usar o editor JS integrado do Mockbird.")

        if tag_lower == "img" and "alt" not in attrs_dict:
            self.warnings.append("Elemento <img> sem atributo 'alt' (recomendado para acessibilidade).")

        if tag_lower not in self.void_tags:
            self.stack.append((tag_lower, self.getpos()))

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self.void_tags:
            return
        if not self.stack:
            self.errors.append(f"Tag de fechamento inesperada </{tag}> na linha {self.getpos()[0]}")
            return
        top, pos = self.stack[-1]
        if top == t:
            self.stack.pop()
        else:
            found_idx = None
            for idx in range(len(self.stack) - 1, -1, -1):
                if self.stack[idx][0] == t:
                    found_idx = idx
                    break
            if found_idx is not None:
                unclosed = [item[0] for item in self.stack[found_idx + 1:]]
                self.errors.append(
                    f"Tags não fechadas antes de </{tag}> na linha {self.getpos()[0]}: {', '.join(unclosed)}"
                )
                self.stack = self.stack[:found_idx]
            else:
                self.errors.append(
                    f"Tag de fechamento </{tag}> sem correspondência de abertura na linha {self.getpos()[0]}"
                )

    def finalize(self):
        while self.stack:
            tag, pos = self.stack.pop()
            self.errors.append(f"Tag <{tag}> aberta na linha {pos[0]} não foi fechada")


# ============================================================================
# Autenticação Exclusiva de Chaves MCP
# ============================================================================


async def get_mcp_auth(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Valida estritamente credenciais MCP via header 'Authorization: Bearer mb_live_...'.
    Rejeita terminantemente JWT de sessão para impedir escalada de privilégios."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial MCP ausente. Forneça o header 'Authorization: Bearer mb_live_...'.",
        )

    token = auth_header.split(" ", 1)[1].strip()
    if not token.startswith("mb_live_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial MCP inválida. Tokens de sessão de usuário não são aceitos no servidor MCP. Crie uma chave de API específica para o MCP.",
        )

    key_hash = hash_mcp_key(token)
    query = await db.execute(
        select(MCPApiKey, User)
        .join(User, User.id == MCPApiKey.user_id)
        .where(MCPApiKey.key_hash == key_hash)
    )
    row = query.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave MCP inválida ou não encontrada",
        )

    mcp_key, user = row[0], row[1]

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário vinculado a esta chave está inativo ou suspenso",
        )

    if mcp_key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave MCP revogada"
        )

    if mcp_key.expires_at and mcp_key.expires_at < utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave MCP expirada"
        )

    # Atualiza timestamp de último uso
    mcp_key.last_used_at = utcnow()
    await db.commit()

    effective_project_ids = list(mcp_key.project_ids or [])
    if not effective_project_ids and mcp_key.project_id:
        effective_project_ids = [mcp_key.project_id]

    return {
        "key": mcp_key,
        "user": user,
        "project_id": mcp_key.project_id or (effective_project_ids[0] if len(effective_project_ids) == 1 else None),
        "project_ids": effective_project_ids,
        "scopes": mcp_key.scopes or [],
    }


def validate_mcp_project_access(auth: Dict[str, Any], target_project_id: Optional[str]) -> None:
    """Valida se o projeto solicitado está na lista autorizada da chave MCP."""
    allowed = auth.get("project_ids") or []
    if not allowed and auth.get("project_id"):
        allowed = [auth["project_id"]]
    if allowed:
        if not target_project_id or target_project_id not in allowed:
            raise HTTPException(
                status_code=403, detail="Esta chave MCP está restrita a outro projeto"
            )


def get_effective_mcp_project_id(auth: Dict[str, Any], requested_id: Optional[str]) -> Optional[str]:
    """Retorna o project_id informado ou infere automaticamente caso a chave tenha escopo unívoco."""
    if requested_id:
        return requested_id
    allowed = auth.get("project_ids") or []
    if not allowed and auth.get("project_id"):
        allowed = [auth["project_id"]]
    if len(allowed) == 1:
        return allowed[0]
    return auth.get("project_id")


async def _build_mcp_key_out(
    mcp_key: MCPApiKey, db: AsyncSession, raw_key: Optional[str] = None
) -> MCPKeyOut:
    pids = list(mcp_key.project_ids or [])
    if not pids and mcp_key.project_id:
        pids = [mcp_key.project_id]

    project_list: List[MCPKeyProjectOut] = []
    project_name = None
    if pids:
        p_query = await db.execute(
            select(Project.id, Project.name)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .where(
                Project.id.in_(pids),
                Workspace.organization_id == mcp_key.organization_id,
            )
        )
        for pid, pname in p_query.all():
            project_list.append(MCPKeyProjectOut(id=pid, name=pname))
        if project_list:
            project_name = ", ".join([p.name for p in project_list])

    return MCPKeyOut(
        id=mcp_key.id,
        name=mcp_key.name,
        prefix=mcp_key.prefix,
        project_id=mcp_key.project_id,
        project_ids=pids,
        projects=project_list,
        project_name=project_name,
        scopes=mcp_key.scopes or [],
        last_used_at=mcp_key.last_used_at,
        expires_at=mcp_key.expires_at,
        revoked_at=mcp_key.revoked_at,
        created_at=mcp_key.created_at,
        raw_key=raw_key,
    )


# ============================================================================
# Endpoints de Gestão de Chaves MCP (Painel do Usuário / Frontend)
# ============================================================================


@router.get("/api/mcp/keys", response_model=List[MCPKeyOut])
async def list_mcp_keys(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Lista as chaves MCP ativas da organização criadas pelo usuário."""
    query = await db.execute(
        select(MCPApiKey)
        .where(
            MCPApiKey.organization_id == current_user.organization_id,
            MCPApiKey.user_id == current_user.id,
        )
        .order_by(MCPApiKey.created_at.desc())
    )
    keys = query.scalars().all()

    all_pids = set()
    for k in keys:
        if k.project_ids:
            all_pids.update(k.project_ids)
        if k.project_id:
            all_pids.add(k.project_id)

    proj_map = {}
    if all_pids:
        p_res = await db.execute(
            select(Project.id, Project.name)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .where(
                Project.id.in_(all_pids),
                Workspace.organization_id == current_user.organization_id,
            )
        )
        proj_map = {row[0]: row[1] for row in p_res.all()}

    results = []
    for k in keys:
        pids = list(k.project_ids or [])
        if not pids and k.project_id:
            pids = [k.project_id]
        project_list = [
            MCPKeyProjectOut(id=pid, name=proj_map.get(pid, f"Projeto {pid[:8]}"))
            for pid in pids
            if pid in proj_map
        ]
        pname = ", ".join([p.name for p in project_list]) if project_list else None
        results.append(
            MCPKeyOut(
                id=k.id,
                name=k.name,
                prefix=k.prefix,
                project_id=k.project_id,
                project_ids=pids,
                projects=project_list,
                project_name=pname,
                scopes=k.scopes or [],
                last_used_at=k.last_used_at,
                expires_at=k.expires_at,
                revoked_at=k.revoked_at,
                created_at=k.created_at,
            )
        )
    return results


@router.post("/api/mcp/keys", response_model=MCPKeyOut)
async def create_mcp_key(
    payload: MCPKeyCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Gera uma nova chave de API para conexão de agentes MCP.
    A chave em texto claro é retornada uma única vez no campo 'raw_key'."""
    target_project_ids = []
    if payload.project_ids is not None:
        target_project_ids = [pid.strip() for pid in payload.project_ids if pid and pid.strip()]
    elif payload.project_id:
        target_project_ids = [payload.project_id.strip()]

    for pid in target_project_ids:
        await authorize_project(pid, current_user, "read", db)

    random_secret = secrets.token_hex(24)
    raw_key = f"mb_live_{random_secret}"
    prefix = f"mb_live_{random_secret[:6]}..."
    key_hash = hash_mcp_key(raw_key)

    expires_at = utcnow() + timedelta(days=payload.expires_in_days or 90)
    primary_project_id = target_project_ids[0] if target_project_ids else None

    mcp_key = MCPApiKey(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        project_id=primary_project_id,
        project_ids=target_project_ids,
        name=payload.name.strip(),
        prefix=prefix,
        key_hash=key_hash,
        scopes=payload.scopes or ["project:read", "screen:write", "export:read"],
        expires_at=expires_at,
    )
    db.add(mcp_key)
    await db.commit()
    await db.refresh(mcp_key)

    return await _build_mcp_key_out(mcp_key, db, raw_key=raw_key)


@router.patch("/api/mcp/keys/{key_id}", response_model=MCPKeyOut)
async def update_mcp_key(
    key_id: str,
    payload: MCPKeyUpdate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Atualiza metadados, projetos permitidos e escopos de uma chave MCP existente."""
    query = await db.execute(
        select(MCPApiKey).where(
            MCPApiKey.id == key_id,
            MCPApiKey.organization_id == current_user.organization_id,
        )
    )
    mcp_key = query.scalars().first()
    if not mcp_key:
        raise HTTPException(status_code=404, detail="Chave MCP não encontrada")

    if mcp_key.user_id != current_user.id and current_user.role not in (
        "admin",
        "owner",
    ):
        raise HTTPException(
            status_code=403,
            detail="Apenas o criador da chave ou um administrador pode editá-la",
        )

    if mcp_key.revoked_at is not None:
        raise HTTPException(
            status_code=400,
            detail="Não é possível editar uma chave MCP revogada",
        )

    if payload.name is not None:
        mcp_key.name = payload.name.strip()

    if payload.scopes is not None:
        mcp_key.scopes = payload.scopes

    if payload.project_ids is not None:
        target_project_ids = [pid.strip() for pid in payload.project_ids if pid and pid.strip()]
        for pid in target_project_ids:
            await authorize_project(pid, current_user, "read", db)
        mcp_key.project_ids = target_project_ids
        mcp_key.project_id = target_project_ids[0] if target_project_ids else None

    await db.commit()
    await db.refresh(mcp_key)

    return await _build_mcp_key_out(mcp_key, db)


@router.delete("/api/mcp/keys/{key_id}")
async def revoke_mcp_key(
    key_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Revoga imediatamente uma chave MCP."""
    query = await db.execute(
        select(MCPApiKey).where(
            MCPApiKey.id == key_id,
            MCPApiKey.organization_id == current_user.organization_id,
        )
    )
    mcp_key = query.scalars().first()
    if not mcp_key:
        raise HTTPException(status_code=404, detail="Chave MCP não encontrada")

    if mcp_key.user_id != current_user.id and current_user.role not in (
        "admin",
        "owner",
    ):
        raise HTTPException(
            status_code=403,
            detail="Apenas o criador da chave ou um administrador pode revogá-la",
        )

    mcp_key.revoked_at = utcnow()
    await db.commit()
    return {"message": "Chave MCP revogada com sucesso", "key_id": key_id}


# ============================================================================
# Definições do Catálogo de Ferramentas MCP
# ============================================================================

MCP_TOOLS_SPEC = [
    {
        "name": "list_projects",
        "description": "Lista todos os projetos acessíveis pela organização do usuário autenticado pela chave MCP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Limite máximo de projetos a retornar (default 50)."}
            },
        },
    },
    {
        "name": "get_project_map",
        "description": "Retorna o mapa do projeto (canvases, telas, IDs, dimensões). Suporta modo resumo (summary_only) e exclusão de tokens para reduzir o tamanho da resposta.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto Mockbird."},
                "include_tokens": {"type": "boolean", "description": "Se falso, omite o bloco de tokens de design. Default: true."},
                "summary_only": {"type": "boolean", "description": "Se verdadeiro, omite tokens e retorna lista compacta de telas. Default: false."}
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_screen",
        "description": "Retorna o código HTML, CSS, JS, dimensões, tokens e metadados de uma tela. Suporta filtros para reduzir tráfego (ex: include_html=false ou fields=['id', 'current_revision']).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela Mockbird."},
                "include_html": {"type": "boolean", "description": "Se falso, não inclui html_content. Default: true."},
                "include_css": {"type": "boolean", "description": "Se falso, não inclui css_content. Default: true."},
                "include_js": {"type": "boolean", "description": "Se falso, não inclui js_content. Default: true."},
                "include_tokens": {"type": "boolean", "description": "Se falso, não inclui tokens. Default: true."},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de campos específicos desejados (ex: ['id', 'name', 'current_revision']).",
                },
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "create_screen",
        "description": "Cria uma nova tela em um canvas ou projeto especificado.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave for vinculada ao projeto)."},
                "name": {"type": "string", "description": "Nome da nova tela."},
                "canvas_id": {"type": "string", "description": "ID do canvas (opcional, usa o canvas padrão se omitido)."},
                "html_content": {"type": "string", "description": "Conteúdo HTML inicial da tela."},
                "css_content": {"type": "string", "description": "CSS customizado opcional."},
                "js_content": {"type": "string", "description": "JavaScript opcional para interatividades."},
                "width": {"type": "integer", "description": "Largura da tela em pixels (default 1440)."},
                "height": {"type": "integer", "description": "Altura da tela em pixels (default 900)."},
                "is_entry": {"type": "boolean", "description": "Se verdadeiro, define esta tela como a inicial do projeto."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "duplicate_screen",
        "description": "Duplica uma tela existente criando uma cópia com novo nome e revisão inicial.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela a ser duplicada."},
                "new_name": {"type": "string", "description": "Nome para a tela duplicada (opcional, default '<nome> (Cópia)')."},
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "delete_screen",
        "description": "Exclui uma tela do projeto (impede exclusão se for a única tela).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela a ser excluída."}
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "patch_screen_element",
        "description": "Aplica uma modificação cirúrgica e atômica em um elemento específico da tela via data-mb-id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "element_mb_id": {"type": "string", "description": "data-mb-id ou id do elemento alvo."},
                "new_html_snippet": {"type": "string", "description": "Novo snippet HTML substituto."},
                "change_summary": {"type": "string", "description": "Descrição resumida da alteração para o histórico."},
            },
            "required": ["screen_id", "element_mb_id", "new_html_snippet"],
        },
    },
    {
        "name": "update_screen_html",
        "description": "Atualiza o código HTML completo de uma tela mantendo o histórico de revisões com auditoria do MCP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "html_content": {"type": "string", "description": "Código HTML completo atualizado."},
                "change_summary": {"type": "string", "description": "Resumo explicativo da alteração."},
                "css_content": {"type": "string", "description": "Código CSS atualizado (opcional)."},
                "js_content": {"type": "string", "description": "Código JS atualizado (opcional)."},
            },
            "required": ["screen_id", "html_content"],
        },
    },
    {
        "name": "batch_update_screens",
        "description": "Atualiza ou cria múltiplas telas em lote para um projeto existente (por screen_id ou screen_name). Evita ter que enviar telas uma por uma em chamadas isoladas, ideal para sincronizar rotas capturadas localmente.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID do projeto Mockbird a ser atualizado. Se omitido, utiliza o projeto vinculado à chave MCP.",
                },
                "screens": {
                    "type": "array",
                    "description": "Lista de telas com HTML a serem atualizadas ou criadas.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "screen_id": {"type": "string", "description": "ID da tela existente (opcional se screen_name for informado)."},
                            "screen_name": {"type": "string", "description": "Nome da tela para correspondência ou criação (ex: 'Login', 'Dashboard', 'Kanban')."},
                            "canvas_name": {"type": "string", "description": "Nome do canvas onde alocar (opcional)."},
                            "html_content": {"type": "string", "description": "Código HTML completo ou fragmento da tela."},
                            "css_content": {"type": "string", "description": "CSS customizado opcional."},
                            "js_content": {"type": "string", "description": "JS customizado opcional."},
                            "viewport": {"type": "string", "enum": ["desktop", "tablet", "mobile"], "description": "Viewport da tela (padrão: desktop)."},
                        },
                        "required": ["html_content"],
                    },
                },
            },
            "required": ["screens"],
        },
    },
    {
        "name": "update_design_tokens",
        "description": "Atualiza os design tokens do projeto (cores, fontes, espaçamentos nos temas light e dark).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto."},
                "light_tokens": {"type": "object", "description": "Dicionário de tokens para tema claro."},
                "dark_tokens": {"type": "object", "description": "Dicionário de tokens para tema escuro."},
                "shared_tokens": {"type": "object", "description": "Dicionário de tokens compartilhados (ex: border radius, tipografia)."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "list_project_assets",
        "description": "Lista todos os arquivos de mídia (logos, imagens, ícones) da biblioteca de assets com URLs assinadas válidas.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto."}
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "list_scenarios",
        "description": "Lista os cenários de dados mockados (mock data) configurados para o projeto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto."}
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "set_scenario_data",
        "description": "Cria ou atualiza um cenário de dados simulados (mock data) para o projeto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto."},
                "name": {"type": "string", "description": "Nome do cenário (ex: 'Estado com 10 Itens', 'Erro 404')."},
                "mock_data": {"type": "object", "description": "Objeto JSON contendo os dados mockados simulados."},
                "scenario_id": {"type": "string", "description": "ID do cenário se for atualização (opcional)."},
            },
            "required": ["project_id", "name", "mock_data"],
        },
    },
    {
        "name": "validate_screen_html",
        "description": "Analisa e valida o código HTML antes de aplicar (detecta tags não fechadas, semântica e IDs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "html_content": {"type": "string", "description": "Código HTML a ser validado."}
            },
            "required": ["html_content"],
        },
    },
    {
        "name": "get_implementation_bundle",
        "description": "Exporta pacote pronto para produção com React JSX limpo, componentes e design tokens.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela para exportação."}
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "render_screen_screenshot",
        "description": "Renderiza visualmente a tela em navegador real headless (Chromium) aplicando tokens de design e CSS, retornando a screenshot da tela (PNG em base64 e imagem nativa MCP) para que a IA comprove a equivalência visual remotamente.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela para captura visual."},
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "tablet", "mobile"],
                    "description": "Tamanho do viewport (desktop: 1440x900, tablet: 768x1024, mobile: 375x812). Padrão: desktop.",
                },
                "theme": {
                    "type": "string",
                    "enum": ["light", "dark"],
                    "description": "Tema visual de design tokens a aplicar ('light' ou 'dark'). Padrão: light.",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "Se verdadeiro, captura a página inteira com scroll.",
                },
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "interact_screen_element",
        "description": "Executa interações reais (clique, preenchimento de input, hover) em um elemento da tela via navegador headless, avalia execução de scripts, navegação mock (data-mb-nav) e mutações no DOM, retornando os efeitos colaterais e a screenshot pós-interação.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela onde está o elemento."},
                "element_mb_id": {
                    "type": "string",
                    "description": "Identificador único do elemento (ex: data-mb-id='btn-checkout' ou 'btn-checkout').",
                },
                "selector": {
                    "type": "string",
                    "description": "Seletor CSS alternativo do elemento (ex: 'button.primary', '#submit-btn').",
                },
                "action": {
                    "type": "string",
                    "enum": ["click", "input", "hover"],
                    "description": "Tipo de interação a executar (padrão: 'click').",
                },
                "input_value": {
                    "type": "string",
                    "description": "Texto a preencher caso a ação seja 'input'.",
                },
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "tablet", "mobile"],
                    "description": "Tamanho do viewport (desktop, tablet, mobile).",
                },
                "theme": {
                    "type": "string",
                    "enum": ["light", "dark"],
                    "description": "Tema visual a aplicar.",
                },
                "capture_screenshot": {
                    "type": "boolean",
                    "description": "Se verdadeiro, captura e retorna a screenshot do resultado após a interação.",
                },
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "restore_screen_revision",
        "description": "Restaura o HTML, CSS e JS de uma tela para uma revisão anterior do seu histórico.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "revision": {"type": "integer", "description": "Número da revisão anterior a restaurar."}
            },
            "required": ["screen_id", "revision"],
        },
    },
    {
        "name": "render_screen_state",
        "description": "Executa uma sequência ordenada de ações interativas (click, input, hover, wait) e captura a screenshot do estado final.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "actions": {
                    "type": "array",
                    "description": "Lista de passos. Ex: [{'action': 'click', 'selector': '#open-btn'}, {'action': 'wait', 'ms': 300}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["click", "input", "hover", "wait"]},
                            "selector": {"type": "string"},
                            "element_mb_id": {"type": "string"},
                            "value": {"type": "string"},
                            "ms": {"type": "integer"}
                        }
                    }
                },
                "viewport": {"type": "string", "enum": ["desktop", "tablet", "mobile"]},
                "theme": {"type": "string", "enum": ["light", "dark"]},
                "full_page": {"type": "boolean"}
            },
            "required": ["screen_id", "actions"],
        },
    },
    {
        "name": "diagnose_screen",
        "description": "Inspeciona scripts, ordem de carga, elementos interativos e erros de console do navegador para a tela.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "viewport": {"type": "string", "enum": ["desktop", "tablet", "mobile"]},
                "theme": {"type": "string", "enum": ["light", "dark"]}
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "validate_screen",
        "description": "Valida uma tela publicada aplicando regras estruturais (suporte a Dark Mode, variantes de viewport, interatividade mínima e integridade estrutural).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela para validação."}
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "import_project_zip",
        "description": "Importa ou atualiza telas e tokens de um projeto existente a partir de um arquivo ZIP em base64.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto existente a atualizar."},
                "zip_base64": {"type": "string", "description": "Conteúdo do arquivo ZIP codificado em base64."},
                "change_summary": {"type": "string", "description": "Descrição da alteração para o histórico de revisões."}
            },
            "required": ["project_id", "zip_base64"],
        },
    },
    {
        "name": "search_screens",
        "description": "Busca leve e paginada de telas por nome, canvas, identificador data-mb-id ou trecho de HTML/CSS/JS sem carregar o mapa completo do projeto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave MCP estiver vinculada a um projeto)."},
                "query": {"type": "string", "description": "Termo de busca livre (procura em nome da tela, canvas, data-mb-id e HTML/CSS/JS)."},
                "name_query": {"type": "string", "description": "Filtro específico por nome da tela (case-insensitive)."},
                "canvas_id": {"type": "string", "description": "Filtra telas de um canvas específico pelo ID."},
                "canvas_name": {"type": "string", "description": "Filtra telas pelo nome do canvas (case-insensitive)."},
                "mb_id": {"type": "string", "description": "Filtra telas que contenham um elemento com este data-mb-id ou id."},
                "html_query": {"type": "string", "description": "Filtra telas que contenham este trecho ou classe no HTML/CSS/JS."},
                "device_type": {"type": "string", "enum": ["desktop", "tablet", "mobile"], "description": "Filtra por tipo de dispositivo/viewport."},
                "is_entry": {"type": "boolean", "description": "Filtra apenas a tela principal de entrada (true/false)."},
                "limit": {"type": "integer", "description": "Máximo de resultados por página (default: 20, máx: 100)."},
                "offset": {"type": "integer", "description": "Deslocamento para paginação (default: 0)."},
                "include_snippet": {"type": "boolean", "description": "Se verdadeiro, inclui trecho de contexto do match e amostra de data-mb-ids. Default: true."}
            },
        },
    },
    {
        "name": "get_design_tokens",
        "description": "Lê isoladamente os Design Tokens atuais do projeto (light, dark, shared) e variáveis CSS equivalentes sem carregar telas ou canvases. (Também acessível via alias 'export_tokens').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave MCP for vinculada a um projeto)."},
                "theme": {
                    "type": "string",
                    "enum": ["all", "light", "dark", "shared"],
                    "description": "Filtra um tema específico ou retorna todos ('all'). Default: 'all'.",
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "css", "dtcg", "all"],
                    "description": "Formato de saída: 'json' (flat dict), 'css' (declarações :root / [data-theme]), 'dtcg' (W3C Design Tokens aninhado) ou 'all'. Default: 'json'.",
                },
            },
        },
    },
    {
        "name": "export_tokens",
        "description": "Alias de get_design_tokens: exporta isoladamente os Design Tokens do projeto nos formatos JSON, CSS custom properties (--*) ou W3C DTCG.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave MCP for vinculada a um projeto)."},
                "theme": {
                    "type": "string",
                    "enum": ["all", "light", "dark", "shared"],
                    "description": "Filtra um tema específico ou retorna todos ('all'). Default: 'all'.",
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "css", "dtcg", "all"],
                    "description": "Formato de saída: 'json', 'css', 'dtcg' ou 'all'. Default: 'all'.",
                },
            },
        },
    },
    {
        "name": "get_component_library",
        "description": "Lista o catálogo de componentes e parciais reutilizáveis do projeto (parciais sincronizadas, blocos extraídos com data-mb-id/data-mb-component e presets token-driven do sistema com slots, variantes e markup base). (Também acessível via alias 'list_components').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave MCP for vinculada a um projeto)."},
                "category": {
                    "type": "string",
                    "description": "Filtra por categoria (ex: 'partial', 'navigation', 'button', 'card', 'input', 'modal', 'table', 'badge').",
                },
                "query": {"type": "string", "description": "Termo de busca por nome, id, slot ou classe do componente."},
                "include_html": {"type": "boolean", "description": "Se verdadeiro, inclui o markup HTML base pronto para uso. Default: true."},
                "include_presets": {"type": "boolean", "description": "Se verdadeiro, inclui também os componentes base token-driven do Design System Mockbird. Default: true."},
            },
        },
    },
    {
        "name": "list_components",
        "description": "Alias de get_component_library: lista componentes reutilizáveis, parciais sincronizadas, slots, variantes e markup base do projeto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave MCP for vinculada a um projeto)."},
                "category": {"type": "string", "description": "Filtra por categoria de componente."},
                "query": {"type": "string", "description": "Busca por nome ou identificador."},
                "include_html": {"type": "boolean", "description": "Inclui o HTML base do componente. Default: true."},
                "include_presets": {"type": "boolean", "description": "Inclui presets token-driven do Design System. Default: true."},
            },
        },
    },
    {
        "name": "compare_screens",
        "description": "Executa diff estrutural (HTML/DOM/CSS/JS e elementos data-mb-id) e diff visual pixel a pixel via Chromium headless entre duas telas diferentes ou entre duas revisões da mesma tela, gerando imagem PNG com highlight das regiões alteradas.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela (quando comparando duas revisões da mesma tela)."},
                "screen_id_a": {"type": "string", "description": "ID da primeira tela (base / antes)."},
                "screen_id_b": {"type": "string", "description": "ID da segunda tela (comparada / depois). Se omitido, usa a mesma tela de screen_id_a/screen_id."},
                "revision_a": {"type": "integer", "description": "Número da revisão inicial (opcional; se omitido ao comparar revisões da mesma tela, usa current_revision - 1)."},
                "revision_b": {"type": "integer", "description": "Número da revisão final (opcional; default: revisão atual da tela B)."},
                "viewport": {"type": "string", "enum": ["desktop", "tablet", "mobile"], "description": "Viewport para renderização do diff visual. Default: desktop."},
                "theme": {"type": "string", "enum": ["light", "dark"], "description": "Tema visual para renderização do diff. Default: light."},
                "full_page": {"type": "boolean", "description": "Se verdadeiro, compara a página inteira com scroll. Default: false."},
                "include_visual_diff": {"type": "boolean", "description": "Se verdadeiro, renderiza ambas no Chromium e gera imagem PNG de pixel diff. Default: true."},
            },
        },
    },
    {
        "name": "list_screen_revisions",
        "description": "Lista o histórico de revisões disponíveis de uma tela (número da revisão, autor, resumo da alteração, data e tamanho) para consulta antes de restore_screen_revision ou compare_screens.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "limit": {"type": "integer", "description": "Máximo de revisões a listar (default: 30)."},
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "get_canvas",
        "description": "Retorna isoladamente um canvas específico (por canvas_id ou canvas_name) ou lista os canvases do projeto com suas telas, dimensões e ordem, sem carregar tokens ou o mapa completo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave for vinculada ao projeto ou se canvas_id for informado)."},
                "canvas_id": {"type": "string", "description": "ID do canvas específico a consultar (opcional)."},
                "canvas_name": {"type": "string", "description": "Nome do canvas a consultar (opcional, case-insensitive)."},
                "include_screens": {"type": "boolean", "description": "Se verdadeiro, inclui a lista de telas de cada canvas retornado. Default: true."},
            },
        },
    },
    {
        "name": "upload_asset",
        "description": "Envia um novo arquivo de mídia (logo, imagem PNG, JPG, SVG, WEBP, GIF) em base64 para a biblioteca de assets do projeto e retorna sua URL assinada pronta para uso em tags <img>.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave for vinculada a um projeto)."},
                "filename": {"type": "string", "description": "Nome original do arquivo (ex: 'logo-brand.svg', 'hero-banner.png')."},
                "data_base64": {"type": "string", "description": "Conteúdo binário do arquivo codificado em base64 (aceita data URI ou base64 puro)."},
                "content_type": {"type": "string", "description": "MIME type do arquivo (ex: 'image/png', 'image/svg+xml', 'image/jpeg', 'image/webp'). Default: 'image/png'."},
            },
            "required": ["filename", "data_base64"],
        },
    },
    {
        "name": "get_screen_comments",
        "description": "Lista os comentários e anotações de revisão ancorados em uma tela e seus elementos (data-mb-id).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "status": {"type": "string", "enum": ["all", "open", "resolved"], "description": "Filtra comentários por status. Default: 'all'."},
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "add_comment",
        "description": "Adiciona um novo comentário/anotação de review em um elemento ou coordenada da tela (ou marca um comentário existente como resolvido).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "body": {"type": "string", "description": "Texto do comentário ou parecer de revisão."},
                "element_mb_id": {"type": "string", "description": "data-mb-id do elemento ao qual o comentário está vinculado (opcional)."},
                "element_snippet": {"type": "string", "description": "Trecho HTML opcional de referência do elemento."},
                "pin_x": {"type": "number", "description": "Posição horizontal relativa do pin em % (0 a 100, default 50)."},
                "pin_y": {"type": "number", "description": "Posição vertical relativa do pin em % (0 a 100, default 50)."},
                "author_name": {"type": "string", "description": "Nome do autor/agente (default: nome da chave MCP)."},
                "resolve_comment_id": {"type": "string", "description": "ID de um comentário existente para anexar resposta e marcar como 'resolved' (opcional)."},
            },
            "required": ["screen_id", "body"],
        },
    },
    {
        "name": "rename_screen",
        "description": "Renomeia uma tela e/ou atualiza seus metadados estruturais (dimensões, device_type, screen_kind, is_entry, posição pos_x/pos_y ou transição) sem precisar reenviar o HTML.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela."},
                "new_name": {"type": "string", "description": "Novo nome da tela."},
                "width": {"type": "integer", "description": "Nova largura em pixels (opcional)."},
                "height": {"type": "integer", "description": "Nova altura em pixels (opcional)."},
                "device_type": {"type": "string", "enum": ["desktop", "tablet", "mobile", "custom"], "description": "Tipo de dispositivo/viewport (opcional)."},
                "screen_kind": {"type": "string", "enum": ["page", "subpage", "modal_overlay"], "description": "Tipo semântico da tela (opcional)."},
                "is_entry": {"type": "boolean", "description": "Se verdadeiro, define esta tela como tela principal de entrada do projeto (opcional)."},
                "pos_x": {"type": "integer", "description": "Coordenada X no canvas (opcional)."},
                "pos_y": {"type": "integer", "description": "Coordenada Y no canvas (opcional)."},
                "transition": {"type": "string", "enum": ["none", "fade", "slide-left"], "description": "Transição de apresentação (opcional)."},
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "move_screen_to_canvas",
        "description": "Move uma tela para outro canvas existente (por target_canvas_id ou target_canvas_name) ou cria automaticamente o canvas de destino no projeto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela a mover."},
                "target_canvas_id": {"type": "string", "description": "ID do canvas de destino (opcional se target_canvas_name for informado)."},
                "target_canvas_name": {"type": "string", "description": "Nome do canvas de destino (cria automaticamente se create_if_missing=true)."},
                "create_if_missing": {"type": "boolean", "description": "Se verdadeiro, cria um novo canvas com target_canvas_name caso não exista. Default: true."},
            },
            "required": ["screen_id"],
        },
    },
    {
        "name": "get_project_settings",
        "description": "Lê (e opcionalmente atualiza) as configurações gerais do projeto além dos tokens: design_dials (variance, motion, density), entry_screen_id, descrição, visibilidade, status de publicação e contadores.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto (opcional se a chave MCP estiver vinculada a um projeto)."},
                "update_name": {"type": "string", "description": "Opcional: atualiza o nome do projeto."},
                "update_description": {"type": "string", "description": "Opcional: atualiza a descrição do projeto."},
                "update_design_dials": {"type": "object", "description": "Opcional: atualiza os dials de design (ex: {'variance': 7, 'motion': 4, 'density': 4})."},
                "update_entry_screen_id": {"type": "string", "description": "Opcional: define o ID da tela principal de entrada do projeto."},
            },
        },
    },
]


# ============================================================================
# Endpoints do Protocolo MCP (/mcp e /mcp/info)
# ============================================================================


@router.get("/mcp")
@router.get("/mcp/info")
async def mcp_server_info():
    """Handshake público seguro com capacidades básicas suportadas."""
    return {
        "name": "mockbird-mcp-server",
        "version": "2.0.0",
        "protocol": "mcp/2024-11-05",
        "description": "Mockbird v2 Design & Prototype Agent Server",
        "auth_required": True,
        "auth_type": "Bearer mb_live_...",
        "tools": MCP_TOOLS_SPEC,
    }


# ============================================================================
# Endpoints REST Individuais para Ferramentas MCP
# ============================================================================


@router.post("/mcp/tools/list_projects")
async def mcp_list_projects(
    payload: Optional[MCPListProjectsRequest] = None,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lista todos os projetos acessíveis pela organização do usuário autenticado pela chave MCP."""
    if "project:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'project:read'"
        )

    user = auth["user"]
    limit = (payload.limit if payload else 50) or 50

    allowed = auth.get("project_ids") or ([] if not auth.get("project_id") else [auth["project_id"]])
    if allowed:
        accessible = []
        for pid in allowed:
            try:
                proj = await authorize_project(pid, user, "read", db)
                accessible.append(
                    {
                        "id": proj.id,
                        "name": proj.name,
                        "slug": proj.slug,
                        "visibility": proj.visibility,
                        "entry_screen_id": proj.entry_screen_id,
                        "created_at": proj.created_at.isoformat() if proj.created_at else None,
                    }
                )
            except HTTPException:
                continue
        return accessible

    query = await db.execute(
        select(Project)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(Workspace.organization_id == user.organization_id)
        .order_by(Project.updated_at.desc())
        .limit(limit)
    )
    all_projects = query.scalars().all()
    accessible = []
    for p in all_projects:
        role = await get_effective_project_role(
            p, user, db, organization_id=user.organization_id
        )
        if role:
            accessible.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "slug": p.slug,
                    "visibility": p.visibility,
                    "entry_screen_id": p.entry_screen_id,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
            )
    return accessible


@router.post("/mcp/tools/get_project_map")
async def mcp_get_project_map(
    project_id: str,
    include_tokens: bool = True,
    summary_only: bool = False,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Retorna mapa de projeto (canvases, telas, tokens) com escopo e tenant verificados."""
    if "project:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'project:read'"
        )

    validate_mcp_project_access(auth, project_id)

    user = auth["user"]
    project = await authorize_project(project_id, user, "read", db)

    tokens = None
    if include_tokens and not summary_only:
        t_query = await db.execute(
            select(DesignTokens).where(DesignTokens.project_id == project_id)
        )
        tokens = t_query.scalars().first()

    c_query = await db.execute(
        select(Canvas)
        .where(Canvas.project_id == project_id)
        .order_by(Canvas.sort_order.asc())
    )
    canvases = c_query.scalars().all()

    canvases_data = []
    for c in canvases:
        s_query = await db.execute(
            select(Screen)
            .where(Screen.canvas_id == c.id)
            .order_by(Screen.created_at.asc())
        )
        screens = s_query.scalars().all()
        canvases_data.append(
            {
                "id": c.id,
                "name": c.name,
                "screens": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "is_entry": s.is_entry,
                        "width": s.width,
                        "height": s.height,
                        "device_type": s.device_type,
                        "current_revision": s.current_revision,
                    }
                    for s in screens
                ],
            }
        )

    result = {
        "project": {
            "id": project.id,
            "name": project.name,
            "slug": project.slug,
            "visibility": project.visibility,
            "entry_screen_id": project.entry_screen_id,
        },
        "canvases": canvases_data,
    }
    if include_tokens and not summary_only:
        result["tokens"] = {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
            "shared": tokens.shared_tokens if tokens else {},
        }
    return result


@router.post("/mcp/tools/get_screen")
async def mcp_get_screen(
    payload: MCPGetScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Retorna o código HTML, CSS, JS, dimensões e tokens completos ou filtrados de uma tela específica."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de projeto/tela"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)

    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas da tela não encontrado")

    validate_mcp_project_access(auth, canvas.project_id)

    tokens = None
    if payload.include_tokens:
        t_query = await db.execute(
            select(DesignTokens).where(DesignTokens.project_id == canvas.project_id)
        )
        tokens = t_query.scalars().first()

    full_data = {
        "id": screen.id,
        "name": screen.name,
        "canvas_id": screen.canvas_id,
        "project_id": canvas.project_id,
        "width": screen.width,
        "height": screen.height,
        "is_entry": screen.is_entry,
        "screen_kind": screen.screen_kind,
        "device_type": screen.device_type,
        "current_revision": screen.current_revision,
        "html_content": screen.html_content if payload.include_html else None,
        "css_content": screen.css_content if payload.include_css else None,
        "js_content": screen.js_content if payload.include_js else None,
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
            "shared": tokens.shared_tokens if tokens else {},
        } if payload.include_tokens else None,
    }

    if payload.fields:
        filtered = {k: v for k, v in full_data.items() if k in payload.fields}
        return filtered

    return full_data


@router.post("/mcp/tools/create_screen")
async def mcp_create_screen(
    payload: MCPCreateScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Cria uma nova tela em um canvas ou projeto especificado."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    proj_id = get_effective_mcp_project_id(auth, payload.project_id)
    if not proj_id and payload.canvas_id:
        c_res = await db.execute(select(Canvas).where(Canvas.id == payload.canvas_id))
        c = c_res.scalars().first()
        if c:
            proj_id = c.project_id

    if not proj_id:
        raise HTTPException(
            status_code=400, detail="project_id é obrigatório para criar uma tela"
        )

    validate_mcp_project_access(auth, proj_id)

    user = auth["user"]
    project = await authorize_project(proj_id, user, "edit", db)

    canvas_id = payload.canvas_id
    if not canvas_id:
        c_res = await db.execute(
            select(Canvas)
            .where(Canvas.project_id == proj_id)
            .order_by(Canvas.sort_order.asc(), Canvas.created_at.asc())
            .limit(1)
        )
        c = c_res.scalars().first()
        if not c:
            c = Canvas(project_id=proj_id, name="Principal")
            db.add(c)
            await db.flush()
        canvas_id = c.id

    default_html = payload.html_content
    if not default_html:
        default_html = (
            f'<div class="min-h-screen bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white p-8">\n'
            f'  <h1 class="text-2xl font-bold mb-4">{payload.name}</h1>\n'
            f'  <p class="text-slate-500 dark:text-slate-400">Nova tela criada via MCP Agent.</p>\n'
            f"</div>"
        )

    screen = Screen(
        canvas_id=canvas_id,
        name=payload.name.strip(),
        is_entry=payload.is_entry or False,
        width=payload.width or 1440,
        height=payload.height or 900,
        html_content=default_html,
        css_content=payload.css_content or "",
        js_content=payload.js_content or "",
        current_revision=1,
    )
    db.add(screen)
    await db.flush()

    if payload.is_entry or not project.entry_screen_id:
        project.entry_screen_id = screen.id

    key_name = auth["key"].name
    rev = ScreenRevision(
        screen_id=screen.id,
        revision_number=1,
        html_content=screen.html_content,
        css_content=screen.css_content,
        js_content=screen.js_content,
        actor=f"mcp:{key_name}",
        change_summary="Criação de tela via MCP Agent",
    )
    db.add(rev)
    await db.commit()
    await db.refresh(screen)

    return {
        "status": "success",
        "screen": {
            "id": screen.id,
            "name": screen.name,
            "canvas_id": screen.canvas_id,
            "project_id": proj_id,
            "width": screen.width,
            "height": screen.height,
            "is_entry": screen.is_entry,
            "current_revision": screen.current_revision,
        },
    }


@router.post("/mcp/tools/duplicate_screen")
async def mcp_duplicate_screen(
    payload: MCPDuplicateScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Duplica uma tela existente criando uma cópia com novo nome e revisão inicial."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    user = auth["user"]
    orig_screen = await authorize_screen(payload.screen_id, user, "edit", db)

    c_res = await db.execute(
        select(Canvas).where(Canvas.id == orig_screen.canvas_id)
    )
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    dup_name = (payload.new_name or f"{orig_screen.name} (Cópia)").strip()
    new_screen = Screen(
        canvas_id=orig_screen.canvas_id,
        name=dup_name,
        is_entry=False,
        screen_kind=orig_screen.screen_kind,
        device_type=orig_screen.device_type,
        width=orig_screen.width,
        height=orig_screen.height,
        pos_x=orig_screen.pos_x + 50,
        pos_y=orig_screen.pos_y + 50,
        html_content=orig_screen.html_content,
        css_content=orig_screen.css_content,
        js_content=orig_screen.js_content,
        transition=orig_screen.transition,
        current_revision=1,
    )
    db.add(new_screen)
    await db.flush()

    key_name = auth["key"].name
    rev = ScreenRevision(
        screen_id=new_screen.id,
        revision_number=1,
        html_content=new_screen.html_content,
        css_content=new_screen.css_content,
        js_content=new_screen.js_content,
        actor=f"mcp:{key_name}",
        change_summary=f"Duplicação da tela '{orig_screen.name}' via MCP Agent",
    )
    db.add(rev)
    await db.commit()
    await db.refresh(new_screen)

    return {
        "status": "success",
        "original_screen_id": orig_screen.id,
        "new_screen": {
            "id": new_screen.id,
            "name": new_screen.name,
            "canvas_id": new_screen.canvas_id,
            "width": new_screen.width,
            "height": new_screen.height,
            "current_revision": new_screen.current_revision,
        },
    }


@router.post("/mcp/tools/delete_screen")
async def mcp_delete_screen(
    payload: MCPDeleteScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Exclui uma tela do projeto (impede exclusão se for a única tela)."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "edit", db)

    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas da tela não encontrado")

    validate_mcp_project_access(auth, canvas.project_id)

    p_res = await db.execute(select(Project).where(Project.id == canvas.project_id))
    project = p_res.scalars().first()

    all_screens_q = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id == canvas.project_id)
    )
    all_screens = all_screens_q.scalars().all()
    if len(all_screens) <= 1:
        raise HTTPException(
            status_code=400, detail="Não é permitido excluir a única tela do projeto."
        )

    if project and project.entry_screen_id == screen.id:
        other = next((s for s in all_screens if s.id != screen.id), None)
        if other:
            project.entry_screen_id = other.id

    await db.delete(screen)
    await db.commit()

    return {
        "status": "success",
        "deleted_screen_id": payload.screen_id,
        "message": f"Tela '{screen.name}' excluída com sucesso",
    }


@router.post("/mcp/tools/patch_screen_element")
async def mcp_patch_screen_element(
    payload: MCPPatchRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Aplica uma modificação cirúrgica em um elemento específico da tela via data-mb-id."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "edit", db)

    canvas_res = await db.execute(
        select(Canvas).where(Canvas.id == screen.canvas_id)
    )
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    clean_id = payload.element_mb_id.lstrip("#").strip()
    if not clean_id:
        raise HTTPException(
            status_code=400,
            detail="Identificador do elemento (data-mb-id) é obrigatório",
        )

    html = screen.html_content
    open_match = re.search(
        rf'<([a-zA-Z0-9\-]+)[^>]*\b(?:data-mb-id|id)=["\']{re.escape(clean_id)}["\'][^>]*>',
        html,
        re.IGNORECASE,
    )
    if not open_match:
        raise HTTPException(
            status_code=404,
            detail=f"Elemento com data-mb-id '{clean_id}' não encontrado no HTML da tela.",
        )

    start_idx = open_match.start()
    tag_name = open_match.group(1).lower()
    full_open = open_match.group(0).rstrip()

    void_tags = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
    if tag_name in void_tags or full_open.endswith("/>"):
        end_idx = open_match.end()
    else:
        pos = open_match.end()
        depth = 1
        tag_re = re.compile(
            rf"(?:<({tag_name})\b[^>]*>)|(?:</({tag_name})\s*>)", re.IGNORECASE
        )
        while depth > 0:
            m = tag_re.search(html, pos)
            if not m:
                break
            if m.group(1):
                if not m.group(0).rstrip().endswith("/>"):
                    depth += 1
            else:
                depth -= 1
            pos = m.end()

        end_idx = pos if depth == 0 else open_match.end()

    new_html = html[:start_idx] + payload.new_html_snippet.strip() + html[end_idx:]

    screen.html_content = new_html
    screen.current_revision += 1

    key_name = auth["key"].name
    rev = ScreenRevision(
        screen_id=screen.id,
        revision_number=screen.current_revision,
        html_content=screen.html_content,
        css_content=screen.css_content,
        js_content=screen.js_content,
        actor=f"mcp:{key_name}",
        change_summary=payload.change_summary or "Patch cirúrgico via MCP Agent",
    )
    db.add(rev)
    await db.commit()
    await db.refresh(screen)

    # Notifica clientes conectados via WebSocket para atualização em tempo real no editor
    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas_obj = c_res.scalars().first()
    if canvas_obj:
        await broadcaster.broadcast(
            canvas_obj.project_id,
            {
                "type": "screen_updated",
                "screen_id": screen.id,
                "origin": f"mcp:{key_name}",
                "name": screen.name,
                "current_revision": screen.current_revision,
                "html_content": screen.html_content,
                "css_content": screen.css_content,
                "js_content": screen.js_content,
            },
        )

    return {
        "status": "success",
        "screen_id": screen.id,
        "revision": screen.current_revision,
        "applied_snippet": payload.new_html_snippet[:150],
        "actor": f"mcp:{key_name}",
    }


@router.post("/mcp/tools/update_screen_html")
async def mcp_update_screen_html(
    payload: MCPUpdateScreenHTMLRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Atualiza o HTML completo de uma tela mantendo o histórico de revisões com autoria MCP."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "edit", db)

    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    screen.html_content = payload.html_content
    if payload.css_content is not None:
        screen.css_content = payload.css_content
    if payload.js_content is not None:
        screen.js_content = payload.js_content

    screen.current_revision += 1
    key_name = auth["key"].name
    rev = ScreenRevision(
        screen_id=screen.id,
        revision_number=screen.current_revision,
        html_content=screen.html_content,
        css_content=screen.css_content,
        js_content=screen.js_content,
        actor=f"mcp:{key_name}",
        change_summary=payload.change_summary or "Atualização completa via MCP Agent",
    )
    db.add(rev)
    await db.commit()
    await db.refresh(screen)

    # Notifica clientes conectados via WebSocket para atualização em tempo real no editor
    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas_obj = c_res.scalars().first()
    if canvas_obj:
        await broadcaster.broadcast(
            canvas_obj.project_id,
            {
                "type": "screen_updated",
                "screen_id": screen.id,
                "origin": f"mcp:{key_name}",
                "name": screen.name,
                "current_revision": screen.current_revision,
                "html_content": screen.html_content,
                "css_content": screen.css_content,
                "js_content": screen.js_content,
            },
        )

    return {
        "status": "success",
        "screen_id": screen.id,
        "revision": screen.current_revision,
        "actor": f"mcp:{key_name}",
        "message": "HTML da tela atualizado com sucesso",
    }


@router.post("/mcp/tools/batch_update_screens")
async def mcp_batch_update_screens(
    payload: MCPBatchUpdateScreensRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Atualiza ou cria múltiplas telas em lote para um projeto existente via MCP."""
    if "screen:write" not in auth["scopes"] and "project:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de escrita de telas/projetos"
        )

    project_id = get_effective_mcp_project_id(auth, payload.project_id)
    if not project_id:
        raise HTTPException(
            status_code=400,
            detail="project_id é obrigatório para atualização de telas em lote.",
        )

    validate_mcp_project_access(auth, project_id)
    user = auth["user"]
    project = await authorize_project(project_id, user, "edit", db)

    # Carrega canvases do projeto
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

    # Carrega telas existentes do projeto
    canvas_ids = [c.id for c in canvases]
    s_res = await db.execute(
        select(Screen).where(Screen.canvas_id.in_(canvas_ids))
    )
    existing_screens = s_res.scalars().all()
    screens_by_id = {s.id: s for s in existing_screens}
    screens_by_name = {s.name.lower().strip(): s for s in existing_screens}

    key_name = auth["key"].name
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
                actor=f"mcp:{key_name}",
                change_summary=item.change_summary or "Atualização em lote via MCP Agent",
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
                actor=f"mcp:{key_name}",
                change_summary=item.change_summary or "Criação em lote via MCP Agent",
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
            "origin": f"mcp:{key_name}",
            "updated_count": len(updated),
            "created_count": len(created),
        },
    )

    return {
        "status": "success",
        "project_id": project.id,
        "total_processed": len(payload.screens),
        "updated_screens": updated,
        "created_screens": created,
        "message": f"{len(updated)} telas atualizadas e {len(created)} telas criadas com sucesso.",
    }


@router.post("/mcp/tools/update_design_tokens")
async def mcp_update_design_tokens(
    payload: MCPUpdateDesignTokensRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Atualiza os design tokens do projeto (cores nos temas light e dark, espaçamentos, etc.)."""
    if "screen:write" not in auth["scopes"] and "project:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de escrita"
        )

    validate_mcp_project_access(auth, payload.project_id)

    user = auth["user"]
    await authorize_project(payload.project_id, user, "edit", db)

    t_res = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == payload.project_id)
    )
    tokens = t_res.scalars().first()
    if not tokens:
        tokens = DesignTokens(
            project_id=payload.project_id,
            light_tokens=payload.light_tokens or {},
            dark_tokens=payload.dark_tokens or {},
            shared_tokens=payload.shared_tokens or {},
        )
        db.add(tokens)
    else:
        if payload.light_tokens is not None:
            current = dict(tokens.light_tokens or {})
            current.update(payload.light_tokens)
            tokens.light_tokens = current
        if payload.dark_tokens is not None:
            current = dict(tokens.dark_tokens or {})
            current.update(payload.dark_tokens)
            tokens.dark_tokens = current
        if payload.shared_tokens is not None:
            current = dict(tokens.shared_tokens or {})
            current.update(payload.shared_tokens)
            tokens.shared_tokens = current

    await db.commit()
    await db.refresh(tokens)

    return {
        "status": "success",
        "project_id": payload.project_id,
        "tokens": {
            "light": tokens.light_tokens,
            "dark": tokens.dark_tokens,
            "shared": tokens.shared_tokens,
        },
    }


@router.post("/mcp/tools/list_project_assets")
async def mcp_list_project_assets(
    payload: MCPListAssetsRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lista todos os arquivos de mídia (logos, imagens, ícones) da biblioteca de assets com URLs assinadas."""
    if "project:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'project:read'"
        )

    validate_mcp_project_access(auth, payload.project_id)

    user = auth["user"]
    await authorize_project(payload.project_id, user, "read", db)

    q = await db.execute(
        select(Asset)
        .where(Asset.project_id == payload.project_id)
        .order_by(Asset.created_at.desc())
    )
    assets = q.scalars().all()

    return [
        {
            "id": a.id,
            "project_id": a.project_id,
            "original_name": a.original_name,
            "content_type": a.content_type,
            "size_bytes": a.size_bytes,
            "url": f"/api/assets/{a.id}?sig={generate_asset_signature(a.id)}",
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in assets
    ]


@router.post("/mcp/tools/list_scenarios")
async def mcp_list_scenarios(
    payload: MCPListScenariosRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lista os cenários de dados mockados (mock data) configurados para o projeto."""
    if "project:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'project:read'"
        )

    validate_mcp_project_access(auth, payload.project_id)

    user = auth["user"]
    await authorize_project(payload.project_id, user, "read", db)

    q = await db.execute(
        select(DataScenario)
        .join(Canvas, Canvas.id == DataScenario.canvas_id)
        .where(Canvas.project_id == payload.project_id)
        .order_by(DataScenario.created_at.asc())
    )
    scenarios = q.scalars().all()

    return [
        {
            "id": sc.id,
            "canvas_id": sc.canvas_id,
            "name": sc.name,
            "mock_data": sc.mock_data,
            "created_at": sc.created_at.isoformat() if sc.created_at else None,
        }
        for sc in scenarios
    ]


@router.post("/mcp/tools/set_scenario_data")
async def mcp_set_scenario_data(
    payload: MCPSetScenarioRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Cria ou atualiza um cenário de dados simulados (mock data) para o projeto."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    validate_mcp_project_access(auth, payload.project_id)

    user = auth["user"]
    await authorize_project(payload.project_id, user, "edit", db)

    c_res = await db.execute(
        select(Canvas)
        .where(Canvas.project_id == payload.project_id)
        .order_by(Canvas.sort_order.asc(), Canvas.created_at.asc())
        .limit(1)
    )
    canvas = c_res.scalars().first()
    if not canvas:
        canvas = Canvas(project_id=payload.project_id, name="Principal")
        db.add(canvas)
        await db.flush()

    if payload.scenario_id:
        sc_res = await db.execute(
            select(DataScenario)
            .join(Canvas, Canvas.id == DataScenario.canvas_id)
            .where(
                DataScenario.id == payload.scenario_id,
                Canvas.project_id == payload.project_id,
            )
        )
        scenario = sc_res.scalars().first()
        if not scenario:
            raise HTTPException(status_code=404, detail="Cenário não encontrado")
        scenario.name = payload.name.strip()
        scenario.mock_data = payload.mock_data
    else:
        scenario = DataScenario(
            canvas_id=canvas.id,
            name=payload.name.strip(),
            mock_data=payload.mock_data,
        )
        db.add(scenario)

    await db.commit()
    await db.refresh(scenario)

    return {
        "status": "success",
        "scenario": {
            "id": scenario.id,
            "canvas_id": scenario.canvas_id,
            "name": scenario.name,
            "mock_data": scenario.mock_data,
        },
    }


@router.post("/mcp/tools/validate_screen_html")
async def mcp_validate_screen_html(
    payload: MCPValidateHTMLRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
):
    """Analisa e valida o código HTML antes de aplicar (detecta tags não fechadas, semântica e IDs)."""
    validator = ScreenHTMLValidator()
    try:
        validator.feed(payload.html_content)
        validator.finalize()
    except Exception as e:
        validator.errors.append(f"Erro no analisador de HTML: {str(e)}")

    is_valid = len(validator.errors) == 0
    return {
        "valid": is_valid,
        "errors": validator.errors,
        "warnings": validator.warnings,
        "elements_with_mb_id": validator.mb_ids,
        "total_tags": validator.total_tags,
    }


@router.post("/mcp/tools/get_implementation_bundle")
async def mcp_get_implementation_bundle(
    screen_id: str,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Devolve pacote pronto para desenvolvedores (JSX React sanitizado + Tokens)."""
    if "project:read" not in auth["scopes"] and "export:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura/exportação"
        )

    user = auth["user"]
    screen = await authorize_screen(screen_id, user, "read", db)

    canvas_res = await db.execute(
        select(Canvas).where(Canvas.id == screen.canvas_id)
    )
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    return {
        "screen_id": screen.id,
        "screen_name": screen.name,
        "html": screen.html_content,
        "css": screen.css_content,
        "react_jsx": html_to_jsx(screen.html_content, screen.name),
    }


@router.post("/mcp/tools/render_screen_screenshot")
async def mcp_render_screen_screenshot(
    payload: MCPRenderScreenshotRequest,
    request: Request,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Renderiza a tela em navegador Chromium headless e gera screenshot fiel aos tokens e viewport."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)

    canvas_res = await db.execute(
        select(Canvas).where(Canvas.id == screen.canvas_id)
    )
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    tok_res = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == canvas.project_id)
    )
    tokens_row = tok_res.scalars().first()
    tokens = {
        "light": tokens_row.light_tokens if tokens_row else {},
        "dark": tokens_row.dark_tokens if tokens_row else {},
        "shared": tokens_row.shared_tokens if tokens_row else {},
    } if tokens_row else {}

    try:
        shot_res = await render_screen_screenshot(
            html_content=screen.html_content or "",
            css_content=screen.css_content or "",
            js_content=screen.js_content or "",
            tokens=tokens,
            viewport_name=payload.viewport or "desktop",
            theme=payload.theme or "light",
            full_page=bool(payload.full_page),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao renderizar screenshot da tela: {str(e)}"
        )

    raw_bytes = shot_res.get("screenshot_bytes")
    asset_url = None
    if raw_bytes:
        try:
            fn = save_asset(canvas.project_id, raw_bytes, "image/png")
            clean_screen_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", screen.name or "screen")
            asset_obj = Asset(
                project_id=canvas.project_id,
                filename=fn,
                original_name=f"screenshot_{clean_screen_name}_{shot_res['viewport']}_{shot_res['theme']}.png",
                content_type="image/png",
                size_bytes=len(raw_bytes),
            )
            db.add(asset_obj)
            await db.commit()
            await db.refresh(asset_obj)
            sig = generate_asset_signature(asset_obj.id)
            asset_url = build_public_url(request, f"/api/assets/{asset_obj.id}?sig={sig}")
        except Exception as asset_err:
            logger.warning(f"Falha ao persistir asset da screenshot: {asset_err}")

    return {
        "status": "success",
        "screen_id": screen.id,
        "screen_name": screen.name,
        "viewport": shot_res["viewport"],
        "theme": shot_res["theme"],
        "width": shot_res["width"],
        "height": shot_res["height"],
        "size_bytes": shot_res["size_bytes"],
        "screenshot_url": asset_url,
        "message": f"Screenshot da tela '{screen.name}' ({shot_res['viewport']}, tema {shot_res['theme']}) gerada com sucesso. Acesse a imagem diretamente em 'screenshot_url' ou visualize o bloco anexado.",
        "image_base64": shot_res["image_base64"],
    }


@router.post("/mcp/tools/interact_screen_element")
async def mcp_interact_screen_element(
    payload: MCPInteractElementRequest,
    request: Request,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Executa interação remota (click, input, hover) em um elemento da tela e analisa mutações no DOM."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)

    canvas_res = await db.execute(
        select(Canvas).where(Canvas.id == screen.canvas_id)
    )
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    tok_res = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == canvas.project_id)
    )
    tokens_row = tok_res.scalars().first()
    tokens = {
        "light": tokens_row.light_tokens if tokens_row else {},
        "dark": tokens_row.dark_tokens if tokens_row else {},
        "shared": tokens_row.shared_tokens if tokens_row else {},
    } if tokens_row else {}

    try:
        interaction_res = await simulate_element_interaction(
            html_content=screen.html_content or "",
            css_content=screen.css_content or "",
            js_content=screen.js_content or "",
            tokens=tokens,
            element_mb_id=payload.element_mb_id,
            selector=payload.selector,
            action=payload.action or "click",
            input_value=payload.input_value,
            viewport_name=payload.viewport or "desktop",
            theme=payload.theme or "light",
            capture_screenshot=payload.capture_screenshot if payload.capture_screenshot is not None else True,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao simular interação no elemento: {str(e)}"
        )

    raw_bytes = interaction_res.pop("screenshot_bytes", None)
    asset_url = None
    if raw_bytes:
        try:
            fn = save_asset(canvas.project_id, raw_bytes, "image/png")
            clean_screen_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", screen.name or "screen")
            asset_obj = Asset(
                project_id=canvas.project_id,
                filename=fn,
                original_name=f"interaction_{clean_screen_name}_{interaction_res['action']}.png",
                content_type="image/png",
                size_bytes=len(raw_bytes),
            )
            db.add(asset_obj)
            await db.commit()
            await db.refresh(asset_obj)
            sig = generate_asset_signature(asset_obj.id)
            asset_url = build_public_url(request, f"/api/assets/{asset_obj.id}?sig={sig}")
        except Exception as asset_err:
            logger.warning(f"Falha ao persistir asset pós-interação: {asset_err}")

    interaction_res["screen_id"] = screen.id
    interaction_res["screen_name"] = screen.name
    interaction_res["screenshot_url"] = asset_url
    return interaction_res


@router.post("/mcp/tools/restore_screen_revision")
async def mcp_restore_screen_revision(
    payload: MCPRestoreScreenRevisionRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Restaura o HTML, CSS e JS de uma tela para uma revisão anterior do seu histórico."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo 'screen:write'")

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "edit", db)

    canvas_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    rev_res = await db.execute(
        select(ScreenRevision).where(
            ScreenRevision.screen_id == screen.id,
            ScreenRevision.revision_number == payload.revision,
        )
    )
    target_rev = rev_res.scalars().first()
    if not target_rev:
        raise HTTPException(
            status_code=404,
            detail=f"Revisão {payload.revision} não encontrada para a tela {screen.id}",
        )

    screen.html_content = target_rev.html_content
    screen.css_content = target_rev.css_content or ""
    screen.js_content = target_rev.js_content or ""
    screen.current_revision += 1

    key_name = auth.get("key_name") or "mcp_key"
    new_rev = ScreenRevision(
        screen_id=screen.id,
        revision_number=screen.current_revision,
        html_content=screen.html_content,
        css_content=screen.css_content,
        js_content=screen.js_content,
        actor=f"mcp:{key_name}",
        change_summary=f"Restaurado para a revisão {payload.revision} via MCP",
    )
    db.add(new_rev)
    await db.commit()
    await db.refresh(screen)

    await broadcaster.broadcast(
        canvas.project_id,
        {
            "type": "screen_updated",
            "screen_id": screen.id,
            "project_id": canvas.project_id,
            "revision": screen.current_revision,
        },
    )

    return {
        "status": "success",
        "message": f"Tela '{screen.name}' restaurada com sucesso para a revisão {payload.revision}.",
        "screen_id": screen.id,
        "restored_from_revision": payload.revision,
        "new_current_revision": screen.current_revision,
    }


@router.post("/mcp/tools/render_screen_state")
async def mcp_render_screen_state(
    payload: MCPRenderScreenStateRequest,
    request: Request,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Executa uma sequência ordenada de ações interativas na tela e extrai screenshot do estado resultante."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos")

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)

    canvas_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    tok_res = await db.execute(select(DesignTokens).where(DesignTokens.project_id == canvas.project_id))
    tokens_row = tok_res.scalars().first()
    tokens = {
        "light": tokens_row.light_tokens if tokens_row else {},
        "dark": tokens_row.dark_tokens if tokens_row else {},
        "shared": tokens_row.shared_tokens if tokens_row else {},
    } if tokens_row else {}

    state_res = await simulate_sequence_interactions(
        html_content=screen.html_content or "",
        actions=payload.actions,
        css_content=screen.css_content or "",
        js_content=screen.js_content or "",
        tokens=tokens,
        viewport_name=payload.viewport or "desktop",
        theme=payload.theme or "light",
        full_page=payload.full_page or False,
    )

    raw_bytes = state_res.pop("screenshot_bytes", None)
    asset_url = None
    if raw_bytes:
        try:
            fn = save_asset(canvas.project_id, raw_bytes, "image/png")
            clean_screen_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", screen.name or "screen")
            asset_obj = Asset(
                project_id=canvas.project_id,
                filename=fn,
                original_name=f"state_{clean_screen_name}_{len(payload.actions)}steps.png",
                content_type="image/png",
                size_bytes=len(raw_bytes),
            )
            db.add(asset_obj)
            await db.commit()
            await db.refresh(asset_obj)
            sig = generate_asset_signature(asset_obj.id)
            asset_url = build_public_url(request, f"/api/assets/{asset_obj.id}?sig={sig}")
        except Exception as asset_err:
            logger.warning(f"Falha ao persistir asset do estado: {asset_err}")

    state_res["screen_id"] = screen.id
    state_res["screen_name"] = screen.name
    state_res["screenshot_url"] = asset_url
    return state_res


@router.post("/mcp/tools/diagnose_screen")
async def mcp_diagnose_screen(
    payload: MCPDiagnoseScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Diagnostica scripts, ordem de carga, elementos interativos e erros de console da tela."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos")

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)

    canvas_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    tok_res = await db.execute(select(DesignTokens).where(DesignTokens.project_id == canvas.project_id))
    tokens_row = tok_res.scalars().first()
    tokens = {
        "light": tokens_row.light_tokens if tokens_row else {},
        "dark": tokens_row.dark_tokens if tokens_row else {},
        "shared": tokens_row.shared_tokens if tokens_row else {},
    } if tokens_row else {}

    diag = await diagnose_screen_structure(
        html_content=screen.html_content or "",
        css_content=screen.css_content or "",
        js_content=screen.js_content or "",
        tokens=tokens,
        viewport_name=payload.viewport or "desktop",
        theme=payload.theme or "light",
    )
    diag["screen_id"] = screen.id
    diag["screen_name"] = screen.name
    diag["current_revision"] = screen.current_revision
    return diag


@router.post("/mcp/tools/validate_screen")
async def mcp_validate_screen(
    payload: MCPValidateScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Valida a tela com as regras estruturais (equivalente a validate.mjs: dark mode, variantes, interatividade)."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos")

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)

    canvas_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = canvas_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    audit = audit_screen_rules(
        html_content=screen.html_content or "",
        css_content=screen.css_content or "",
        js_content=screen.js_content or "",
    )
    audit["screen_id"] = screen.id
    audit["screen_name"] = screen.name
    audit["current_revision"] = screen.current_revision
    return audit


@router.post("/mcp/tools/import_project_zip")
async def mcp_import_project_zip(
    payload: MCPImportProjectZipRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Importa ou atualiza telas e tokens de um projeto existente a partir de um arquivo ZIP em base64."""
    if "project:write" not in auth["scopes"] and "screen:write" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo de escrita de projeto/tela")

    proj_id = get_effective_mcp_project_id(auth, payload.project_id)
    if not proj_id:
        raise HTTPException(status_code=400, detail="project_id é obrigatório")
    validate_mcp_project_access(auth, proj_id)

    user = auth["user"]
    project = await authorize_project(proj_id, user, "edit", db)

    try:
        raw_zip = base64.b64decode(payload.zip_base64)
    except Exception as b64_err:
        raise HTTPException(status_code=400, detail=f"Base64 do ZIP inválido: {str(b64_err)}")

    try:
        parsed = parse_design_corpus(raw_zip)
    except DesignCorpusError as dce:
        raise HTTPException(status_code=400, detail=str(dce))

    key_name = auth.get("key_name") or "mcp_key"
    res = await apply_design_corpus_to_project(
        parsed=parsed,
        project=project,
        actor_name=f"mcp:{key_name}",
        user_id=user.id,
        db=db,
        change_summary=payload.change_summary or "Atualização via MCP ZIP Import",
    )

    return {
        "status": "success",
        "message": f"ZIP importado com sucesso para o projeto '{project.name}'.",
        "project_id": project.id,
        "canvases": res["canvases"],
        "screens": res["screens"],
        "updated_screens": res["updated_screens"],
        "created_screens": res["created_screens"],
        "warnings": res["warnings"],
    }


# ============================================================================
# Ferramentas Avançadas de Produtividade MCP (Search, Tokens, Components, Diff, Revisions, Canvases, Assets, Comments)
# ============================================================================

DEFAULT_DESIGN_SYSTEM_COMPONENTS: List[Dict[str, Any]] = [
    {
        "id": "mb-btn-primary",
        "name": "Button (Token-Driven)",
        "category": "button",
        "source": "design_system_preset",
        "description": "Botão interativo padronizado com suporte a temas light/dark, tokens de cor primária e estados de foco/hover.",
        "slots": ["icon-left", "label", "icon-right"],
        "variants": {
            "size": ["sm", "md", "lg"],
            "tone": ["primary", "secondary", "outline", "ghost", "danger"],
            "state": ["default", "hover", "active", "disabled", "loading"],
        },
        "tokens_used": ["--color-primary", "--color-surface", "--color-text", "--color-border"],
        "marker_syntax": 'data-mb-component="button" data-mb-id="btn-action"',
        "base_html": (
            '<button data-mb-component="button" data-mb-id="btn-primary-action" type="button" '
            'class="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm '
            'bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/40">\n'
            '  <span>Confirmar Ação</span>\n'
            '</button>'
        ),
    },
    {
        "id": "mb-card-surface",
        "name": "Surface Card",
        "category": "card",
        "source": "design_system_preset",
        "description": "Contêiner de superfície elevado com header, body e footer estruturados e suporte nativo a dark mode.",
        "slots": ["card-header", "card-title", "card-actions", "card-body", "card-footer"],
        "variants": {
            "size": ["compact", "default", "spacious"],
            "tone": ["default", "elevated", "bordered", "highlighted"],
            "state": ["default", "interactive", "selected"],
        },
        "tokens_used": ["--color-surface", "--color-bg", "--color-text", "--color-border"],
        "marker_syntax": '<!-- PARTIAL:card-surface --> ... <!-- /PARTIAL:card-surface -->',
        "base_html": (
            '<div data-mb-component="card" data-mb-id="card-container" '
            'class="rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-5 shadow-sm">\n'
            '  <div class="flex items-center justify-between mb-3">\n'
            '    <h3 data-mb-id="card-title" class="text-base font-semibold text-slate-900 dark:text-white">Título do Card</h3>\n'
            '    <span class="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-medium">Ativo</span>\n'
            '  </div>\n'
            '  <p data-mb-id="card-body" class="text-sm text-slate-600 dark:text-slate-400">Conteúdo descritivo do componente reutilizável.</p>\n'
            '</div>'
        ),
    },
    {
        "id": "mb-input-field",
        "name": "Form Input Field",
        "category": "input",
        "source": "design_system_preset",
        "description": "Campo de entrada com label, estado de validação, helper text e ícone opcional.",
        "slots": ["label", "input", "prefix-icon", "helper-text", "error-message"],
        "variants": {
            "size": ["sm", "md", "lg"],
            "tone": ["default", "error", "success"],
            "state": ["default", "focused", "disabled", "readonly"],
        },
        "tokens_used": ["--color-surface", "--color-text", "--color-border", "--color-primary"],
        "marker_syntax": 'data-mb-component="input-field" data-mb-id="field-wrapper"',
        "base_html": (
            '<div data-mb-component="input-field" data-mb-id="field-group" class="flex flex-col gap-1.5">\n'
            '  <label class="text-xs font-semibold text-slate-700 dark:text-slate-300">Nome do Campo</label>\n'
            '  <input data-mb-id="input-control" type="text" placeholder="Digite aqui..." '
            'class="w-full px-3.5 py-2 rounded-lg text-sm bg-white dark:bg-slate-950 border border-slate-300 dark:border-slate-800 '
            'text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/40" />\n'
            '</div>'
        ),
    },
    {
        "id": "mb-modal-dialog",
        "name": "Modal Dialog Overlay",
        "category": "modal",
        "source": "design_system_preset",
        "description": "Janela modal com backdrop, cabeçalho com botão fechar, corpo rolável e barra de ações.",
        "slots": ["modal-header", "modal-title", "modal-close", "modal-body", "modal-footer"],
        "variants": {
            "size": ["sm", "md", "lg", "xl"],
            "tone": ["default", "danger", "info"],
            "state": ["open", "hidden"],
        },
        "tokens_used": ["--color-surface", "--color-text", "--color-border"],
        "marker_syntax": '<!-- PARTIAL:modal-dialog --> ... <!-- /PARTIAL:modal-dialog -->',
        "base_html": (
            '<div data-mb-component="modal" data-mb-id="modal-overlay" '
            'class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 backdrop-blur-xs p-4">\n'
            '  <div data-mb-id="modal-content" class="w-full max-w-lg rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden">\n'
            '    <div class="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-800">\n'
            '      <h3 class="text-base font-bold text-slate-900 dark:text-white">Título do Modal</h3>\n'
            '      <button data-mb-id="modal-close-btn" type="button" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">✕</button>\n'
            '    </div>\n'
            '    <div class="p-5 text-sm text-slate-600 dark:text-slate-300">Corpo do modal.</div>\n'
            '    <div class="flex items-center justify-end gap-2 px-5 py-3.5 bg-slate-50 dark:bg-slate-950/50 border-t border-slate-200 dark:border-slate-800">\n'
            '      <button data-mb-id="modal-cancel-btn" type="button" class="px-3.5 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-400">Cancelar</button>\n'
            '      <button data-mb-id="modal-confirm-btn" type="button" class="px-4 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white">Salvar</button>\n'
            '    </div>\n'
            '  </div>\n'
            '</div>'
        ),
    },
    {
        "id": "mb-nav-sidebar",
        "name": "Sidebar Navigation Partial",
        "category": "navigation",
        "source": "design_system_preset",
        "description": "Barra lateral de navegação sincronizável entre telas via marcador de parcial e links data-mb-nav.",
        "slots": ["brand-logo", "nav-items", "user-profile-footer"],
        "variants": {
            "size": ["collapsed", "expanded"],
            "tone": ["surface", "inverted"],
            "state": ["active-item", "default-item"],
        },
        "tokens_used": ["--color-surface", "--color-bg", "--color-text", "--color-primary", "--color-border"],
        "marker_syntax": '<!-- PARTIAL:sidebar --> ... <!-- /PARTIAL:sidebar -->',
        "base_html": (
            '<!-- PARTIAL:sidebar -->\n'
            '<aside data-mb-component="sidebar" data-mb-id="app-sidebar" '
            'class="w-64 shrink-0 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 flex flex-col justify-between p-4">\n'
            '  <div class="space-y-4">\n'
            '    <div data-mb-id="sidebar-brand" class="px-2 py-1 text-lg font-bold text-slate-900 dark:text-white">BrandApp</div>\n'
            '    <nav data-mb-id="sidebar-nav" class="flex flex-col gap-1">\n'
            '      <a data-mb-id="nav-dashboard" data-mb-nav="dashboard" href="#" class="px-3 py-2 rounded-lg text-sm font-medium bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">Dashboard</a>\n'
            '      <a data-mb-id="nav-settings" data-mb-nav="settings" href="#" class="px-3 py-2 rounded-lg text-sm font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">Configurações</a>\n'
            '    </nav>\n'
            '  </div>\n'
            '</aside>\n'
            '<!-- /PARTIAL:sidebar -->'
        ),
    },
    {
        "id": "mb-status-badge",
        "name": "Status Badge / Pill",
        "category": "badge",
        "source": "design_system_preset",
        "description": "Indicador compacto de status, tag ou categoria semântica.",
        "slots": ["dot-indicator", "label"],
        "variants": {
            "size": ["xs", "sm", "md"],
            "tone": ["neutral", "success", "warning", "danger", "info"],
            "state": ["solid", "subtle", "outline"],
        },
        "tokens_used": ["--color-primary", "--color-surface", "--color-text"],
        "marker_syntax": 'data-mb-component="badge"',
        "base_html": (
            '<span data-mb-component="badge" data-mb-id="status-badge" '
            'class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">\n'
            '  <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>\n'
            '  <span>Concluído</span>\n'
            '</span>'
        ),
    },
]


@router.post("/mcp/tools/search_screens")
async def mcp_search_screens(
    payload: MCPSearchScreensRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Busca leve e paginada de telas por nome, canvas, data-mb-id ou trecho de HTML/CSS/JS."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de projeto/telas"
        )

    proj_id = get_effective_mcp_project_id(auth, payload.project_id)
    user = auth["user"]

    if proj_id:
        validate_mcp_project_access(auth, proj_id)
        project = await authorize_project(proj_id, user, "read", db)
        target_project_ids = [project.id]
    else:
        allowed = auth.get("project_ids") or ([] if not auth.get("project_id") else [auth["project_id"]])
        if allowed:
            target_project_ids = []
            for pid in allowed:
                try:
                    p = await authorize_project(pid, user, "read", db)
                    target_project_ids.append(p.id)
                except HTTPException:
                    continue
        else:
            p_res = await db.execute(
                select(Project)
                .join(Workspace, Workspace.id == Project.workspace_id)
                .where(Workspace.organization_id == user.organization_id)
            )
            target_project_ids = [p.id for p in p_res.scalars().all()]

    if not target_project_ids:
        return {
            "total_matches": 0,
            "limit": payload.limit or 20,
            "offset": payload.offset or 0,
            "has_more": False,
            "screens": [],
        }

    stmt = (
        select(Screen, Canvas)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .where(Canvas.project_id.in_(target_project_ids))
        .order_by(Canvas.sort_order.asc(), Screen.created_at.asc())
    )
    if payload.canvas_id:
        stmt = stmt.where(Canvas.id == payload.canvas_id)
    if payload.device_type:
        stmt = stmt.where(Screen.device_type == payload.device_type.lower().strip())
    if payload.is_entry is not None:
        stmt = stmt.where(Screen.is_entry == bool(payload.is_entry))

    rows = (await db.execute(stmt)).all()

    q_general = (payload.query or "").strip().lower()
    q_name = (payload.name_query or "").strip().lower()
    q_canvas = (payload.canvas_name or "").strip().lower()
    q_mb_id = (payload.mb_id or "").strip().lower().lstrip("#")
    q_html = (payload.html_query or "").strip().lower()

    matched_items: List[Dict[str, Any]] = []
    mb_id_re = re.compile(r'\b(?:data-mb-id|id)=["\']([^"\']+)["\']', re.IGNORECASE)

    for screen, canvas in rows:
        s_name_l = (screen.name or "").lower()
        c_name_l = (canvas.name or "").lower()
        html_raw = screen.html_content or ""
        css_raw = screen.css_content or ""
        js_raw = screen.js_content or ""
        html_l = html_raw.lower()
        css_l = css_raw.lower()
        js_l = js_raw.lower()

        screen_mb_ids = mb_id_re.findall(html_raw)
        screen_mb_ids_l = [m.lower() for m in screen_mb_ids]

        if q_name and q_name not in s_name_l:
            continue
        if q_canvas and q_canvas not in c_name_l:
            continue
        if q_mb_id and not any(q_mb_id in mid for mid in screen_mb_ids_l):
            continue
        if q_html and (q_html not in html_l and q_html not in css_l and q_html not in js_l):
            continue

        matched_in: List[str] = []
        snippet_preview: Optional[str] = None

        if q_general:
            if q_general in s_name_l:
                matched_in.append("screen_name")
            if q_general in c_name_l:
                matched_in.append("canvas_name")
            if any(q_general in mid for mid in screen_mb_ids_l):
                matched_in.append("data-mb-id")
            idx_html = html_l.find(q_general)
            if idx_html != -1:
                matched_in.append("html")
                start_snip = max(0, idx_html - 60)
                end_snip = min(len(html_raw), idx_html + len(q_general) + 100)
                snippet_preview = re.sub(r"\s+", " ", html_raw[start_snip:end_snip]).strip()
            if q_general in css_l:
                matched_in.append("css")
            if q_general in js_l:
                matched_in.append("js")
            if not matched_in:
                continue
        else:
            if q_name:
                matched_in.append("screen_name")
            if q_canvas:
                matched_in.append("canvas_name")
            if q_mb_id:
                matched_in.append("data-mb-id")
            if q_html:
                matched_in.append("html")
                idx_h = html_l.find(q_html)
                if idx_h != -1:
                    start_snip = max(0, idx_h - 60)
                    end_snip = min(len(html_raw), idx_h + len(q_html) + 100)
                    snippet_preview = re.sub(r"\s+", " ", html_raw[start_snip:end_snip]).strip()
            if not matched_in:
                matched_in.append("filter")

        if payload.include_snippet and not snippet_preview and html_raw:
            snippet_preview = re.sub(r"\s+", " ", html_raw[:160]).strip()

        item: Dict[str, Any] = {
            "id": screen.id,
            "name": screen.name,
            "canvas_id": canvas.id,
            "canvas_name": canvas.name,
            "project_id": canvas.project_id,
            "width": screen.width,
            "height": screen.height,
            "device_type": screen.device_type,
            "screen_kind": screen.screen_kind,
            "is_entry": screen.is_entry,
            "current_revision": screen.current_revision,
            "matched_in": matched_in,
        }
        if payload.include_snippet:
            item["mb_ids_sample"] = list(dict.fromkeys(screen_mb_ids))[:15]
            item["total_mb_ids"] = len(set(screen_mb_ids))
            item["html_snippet"] = snippet_preview

        matched_items.append(item)

    limit = max(1, min(int(payload.limit or 20), 100))
    offset = max(0, int(payload.offset or 0))
    total = len(matched_items)
    paginated = matched_items[offset : offset + limit]

    return {
        "status": "success",
        "total_matches": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total,
        "screens": paginated,
    }


def _build_css_tokens_export(
    light_tokens: Dict[str, Any],
    dark_tokens: Dict[str, Any],
    shared_tokens: Dict[str, Any],
) -> str:
    """Converte dicionários de design tokens em folha de variáveis CSS (:root e [data-theme='dark'])."""
    root_vars = {**(shared_tokens or {}), **(light_tokens or {})}
    dark_vars = dict(dark_tokens or {})

    lines = [":root, [data-theme=\"light\"] {"]
    for k, v in sorted(root_vars.items()):
        if isinstance(v, (dict, list)):
            continue
        clean_k = str(k).lstrip("-")
        lines.append(f"  --{clean_k}: {v};")
    lines.append("}")

    if dark_vars:
        lines.append("")
        lines.append(".dark, [data-theme=\"dark\"] {")
        for k, v in sorted(dark_vars.items()):
            if isinstance(v, (dict, list)):
                continue
            clean_k = str(k).lstrip("-")
            lines.append(f"  --{clean_k}: {v};")
        lines.append("}")

    return "\n".join(lines)


@router.post("/mcp/tools/get_design_tokens")
@router.post("/mcp/tools/export_tokens")
async def mcp_get_design_tokens(
    payload: Optional[MCPGetDesignTokensRequest] = None,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lê ou exporta isoladamente os Design Tokens do projeto nos formatos JSON, CSS custom properties ou W3C DTCG."""
    if "project:read" not in auth["scopes"] and "export:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de projeto/tokens"
        )

    req = payload or MCPGetDesignTokensRequest()
    proj_id = get_effective_mcp_project_id(auth, req.project_id)
    if not proj_id:
        raise HTTPException(status_code=400, detail="project_id é obrigatório")

    validate_mcp_project_access(auth, proj_id)
    user = auth["user"]
    project = await authorize_project(proj_id, user, "read", db)

    t_res = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == proj_id)
    )
    tokens_row = t_res.scalars().first()

    light = dict(tokens_row.light_tokens or {}) if tokens_row else {}
    dark = dict(tokens_row.dark_tokens or {}) if tokens_row else {}
    shared = dict(tokens_row.shared_tokens or {}) if tokens_row else {}
    # Oculta chave interna 'components' se houver no shared_tokens ao listar apenas tokens puros
    shared_clean = {k: v for k, v in shared.items() if k != "components"}

    theme_filter = (req.theme or "all").lower().strip()
    fmt = (req.format or "json").lower().strip()

    tokens_out: Dict[str, Any] = {}
    if theme_filter in ("all", "light"):
        tokens_out["light"] = light
    if theme_filter in ("all", "dark"):
        tokens_out["dark"] = dark
    if theme_filter in ("all", "shared"):
        tokens_out["shared"] = shared_clean

    result: Dict[str, Any] = {
        "status": "success",
        "project_id": project.id,
        "project_name": project.name,
        "theme": theme_filter,
        "format": fmt,
        "token_counts": {
            "light": len(light),
            "dark": len(dark),
            "shared": len(shared_clean),
        },
    }

    if fmt in ("json", "all"):
        result["tokens"] = tokens_out
    if fmt in ("css", "all"):
        result["css_variables"] = _build_css_tokens_export(
            light if theme_filter in ("all", "light") else {},
            dark if theme_filter in ("all", "dark") else {},
            shared_clean if theme_filter in ("all", "shared") else {},
        )
    if fmt in ("dtcg", "all"):
        result["dtcg"] = {
            "light": nest_tokens(light) if theme_filter in ("all", "light") else {},
            "dark": nest_tokens(dark) if theme_filter in ("all", "dark") else {},
            "shared": nest_tokens(shared_clean) if theme_filter in ("all", "shared") else {},
        }

    return result


def _extract_components_from_project_screens(
    screens: List[Screen],
) -> List[Dict[str, Any]]:
    """Inspeciona o HTML das telas do projeto para descobrir parciais (<!-- PARTIAL:x -->) e componentes (data-mb-component / data-mb-id recorrentes)."""
    discovered: Dict[str, Dict[str, Any]] = {}

    # 1. Parciais explícitas: <!-- PARTIAL:name --> ... <!-- /PARTIAL:name --> ou <!-- COMPONENT:name -->
    partial_re = re.compile(
        r"<!--\s*(?:PARTIAL|COMPONENT):([a-zA-Z0-9_\-]+)\s*-->(.*?)<!--\s*/(?:PARTIAL|COMPONENT):\1\s*-->",
        re.IGNORECASE | re.DOTALL,
    )

    # 2. Elementos marcados com data-mb-component="name"
    comp_attr_re = re.compile(
        r'<([a-zA-Z0-9\-]+)([^>]*\bdata-(?:mb-)?component=["\']([^"\']+)["\'][^>]*)>',
        re.IGNORECASE,
    )

    # 3. Blocos semânticos identificáveis por tag/data-mb-id (nav, aside, header, footer, dialog, modal, sidebar, card, form, table)
    semantic_re = re.compile(
        r'<([a-zA-Z0-9\-]+)([^>]*\b(?:data-mb-id|id)=["\']([a-zA-Z0-9_\-]+)["\'][^>]*)>',
        re.IGNORECASE,
    )

    token_var_re = re.compile(r"var\((--[a-zA-Z0-9_\-]+)")
    slot_re = re.compile(r'\b(?:data-mb-slot|data-slot|data-mb-id)=["\']([^"\']+)["\']', re.IGNORECASE)

    def _extract_outer_html(html: str, start_idx: int, tag_name: str, open_end_idx: int) -> str:
        void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        if tag_name in void_tags or html[start_idx:open_end_idx].rstrip().endswith("/>"):
            return html[start_idx:open_end_idx]
        pos = open_end_idx
        depth = 1
        t_re = re.compile(rf"(?:<({tag_name})\b[^>]*>)|(?:</({tag_name})\s*>)", re.IGNORECASE)
        while depth > 0:
            m = t_re.search(html, pos)
            if not m:
                break
            if m.group(1):
                if not m.group(0).rstrip().endswith("/>"):
                    depth += 1
            else:
                depth -= 1
            pos = m.end()
        end_idx = pos if depth == 0 else min(len(html), open_end_idx + 400)
        return html[start_idx:end_idx]

    def _infer_category(name_or_id: str, tag: str) -> str:
        key = f"{name_or_id} {tag}".lower()
        if any(w in key for w in ("nav", "sidebar", "header", "topbar", "menu", "breadcrumb", "tab")):
            return "navigation"
        if any(w in key for w in ("btn", "button", "cta", "action")):
            return "button"
        if any(w in key for w in ("modal", "dialog", "drawer", "popover", "sheet")):
            return "modal"
        if any(w in key for w in ("input", "field", "select", "search", "form", "checkbox", "toggle")):
            return "input"
        if any(w in key for w in ("table", "grid", "list", "row")):
            return "table"
        if any(w in key for w in ("badge", "pill", "tag", "chip", "status")):
            return "badge"
        if any(w in key for w in ("card", "panel", "widget", "stat", "metric")):
            return "card"
        return "partial"

    for s in screens:
        html = s.html_content or ""
        if not html:
            continue

        # 1. Parciais por comentário
        for pm in partial_re.finditer(html):
            p_name = pm.group(1).strip()
            p_body = pm.group(2).strip()
            key = f"partial:{p_name.lower()}"
            full_markup = f"<!-- PARTIAL:{p_name} -->\n{p_body}\n<!-- /PARTIAL:{p_name} -->"
            slots = list(dict.fromkeys(slot_re.findall(p_body)))[:12]
            tokens_used = list(dict.fromkeys(token_var_re.findall(p_body)))
            if key not in discovered:
                discovered[key] = {
                    "id": p_name,
                    "name": f"Partial: {p_name}",
                    "category": _infer_category(p_name, "partial"),
                    "source": "project_partial",
                    "description": f"Parcial sincronizada '{p_name}' extraída das telas do projeto.",
                    "slots": slots,
                    "variants": {"theme": ["light", "dark"]},
                    "tokens_used": tokens_used,
                    "marker_syntax": f"<!-- PARTIAL:{p_name} --> ... <!-- /PARTIAL:{p_name} -->",
                    "usage_count": 1,
                    "used_in_screens": [{"id": s.id, "name": s.name}],
                    "base_html": full_markup[:2500],
                }
            else:
                discovered[key]["usage_count"] += 1
                if not any(x["id"] == s.id for x in discovered[key]["used_in_screens"]):
                    discovered[key]["used_in_screens"].append({"id": s.id, "name": s.name})

        # 2. Elementos com data-mb-component
        for cm in comp_attr_re.finditer(html):
            tag = cm.group(1).lower()
            c_name = cm.group(3).strip()
            key = f"comp:{c_name.lower()}"
            outer = _extract_outer_html(html, cm.start(), tag, cm.end())
            slots = list(dict.fromkeys(slot_re.findall(outer)))[:12]
            tokens_used = list(dict.fromkeys(token_var_re.findall(outer)))
            if key not in discovered:
                discovered[key] = {
                    "id": c_name,
                    "name": c_name.replace("-", " ").title(),
                    "category": _infer_category(c_name, tag),
                    "source": "project_component",
                    "description": f"Componente '{c_name}' registrado com data-mb-component nas telas do projeto.",
                    "slots": slots,
                    "variants": {"theme": ["light", "dark"]},
                    "tokens_used": tokens_used,
                    "marker_syntax": f'data-mb-component="{c_name}"',
                    "usage_count": 1,
                    "used_in_screens": [{"id": s.id, "name": s.name}],
                    "base_html": outer[:2500],
                }
            else:
                discovered[key]["usage_count"] += 1
                if not any(x["id"] == s.id for x in discovered[key]["used_in_screens"]):
                    discovered[key]["used_in_screens"].append({"id": s.id, "name": s.name})

        # 3. Elementos semânticos com data-mb-id (sidebar, navbar, header, modal, card, btn, input, table)
        for sm in semantic_re.finditer(html):
            tag = sm.group(1).lower()
            el_id = sm.group(3).strip()
            cat = _infer_category(el_id, tag)
            if cat == "partial" and tag not in ("nav", "aside", "header", "footer", "dialog", "form", "table"):
                continue
            key = f"el:{el_id.lower()}"
            if key in discovered:
                discovered[key]["usage_count"] += 1
                if not any(x["id"] == s.id for x in discovered[key]["used_in_screens"]):
                    discovered[key]["used_in_screens"].append({"id": s.id, "name": s.name})
                continue
            outer = _extract_outer_html(html, sm.start(), tag, sm.end())
            slots = [sl for sl in dict.fromkeys(slot_re.findall(outer)) if sl != el_id][:10]
            tokens_used = list(dict.fromkeys(token_var_re.findall(outer)))
            discovered[key] = {
                "id": el_id,
                "name": el_id.replace("-", " ").replace("_", " ").title(),
                "category": cat,
                "source": "extracted_from_screens",
                "description": f"Bloco reutilizável '<{tag} data-mb-id=\"{el_id}\">' detectado no projeto.",
                "slots": slots,
                "variants": {"theme": ["light", "dark"]},
                "tokens_used": tokens_used,
                "marker_syntax": f'data-mb-id="{el_id}"',
                "usage_count": 1,
                "used_in_screens": [{"id": s.id, "name": s.name}],
                "base_html": outer[:2000],
            }

    # Ordena priorizando parciais explícitas e componentes mais reutilizados entre telas
    sorted_list = sorted(
        discovered.values(),
        key=lambda c: (
            0 if c["source"] in ("project_partial", "project_component") else 1,
            -int(c.get("usage_count", 1)),
            c["id"],
        ),
    )
    return sorted_list


@router.post("/mcp/tools/get_component_library")
@router.post("/mcp/tools/list_components")
async def mcp_get_component_library(
    payload: Optional[MCPGetComponentLibraryRequest] = None,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lista o catálogo de componentes e parciais reutilizáveis do projeto (extraídos das telas, registrados em tokens e presets do Design System)."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de projeto/componentes"
        )

    req = payload or MCPGetComponentLibraryRequest()
    proj_id = get_effective_mcp_project_id(auth, req.project_id)
    user = auth["user"]

    project_components: List[Dict[str, Any]] = []
    custom_registered: List[Dict[str, Any]] = []
    project_name = None

    if proj_id:
        validate_mcp_project_access(auth, proj_id)
        project = await authorize_project(proj_id, user, "read", db)
        project_name = project.name

        t_res = await db.execute(
            select(DesignTokens).where(DesignTokens.project_id == proj_id)
        )
        tokens_row = t_res.scalars().first()
        if tokens_row and isinstance(tokens_row.shared_tokens, dict):
            raw_comps = tokens_row.shared_tokens.get("components")
            if isinstance(raw_comps, list):
                for rc in raw_comps:
                    if isinstance(rc, dict) and rc.get("id"):
                        custom_registered.append({
                            "source": "project_registered",
                            "usage_count": rc.get("usage_count", 1),
                            **rc,
                        })
            elif isinstance(raw_comps, dict):
                for cid, rc in raw_comps.items():
                    if isinstance(rc, dict):
                        custom_registered.append({
                            "id": cid,
                            "name": rc.get("name", cid),
                            "category": rc.get("category", "partial"),
                            "source": "project_registered",
                            "slots": rc.get("slots", []),
                            "variants": rc.get("variants", {}),
                            "base_html": rc.get("base_html") or rc.get("html", ""),
                            **rc,
                        })

        s_res = await db.execute(
            select(Screen)
            .join(Canvas, Canvas.id == Screen.canvas_id)
            .where(Canvas.project_id == proj_id)
            .order_by(Canvas.sort_order.asc(), Screen.created_at.asc())
        )
        screens = s_res.scalars().all()
        project_components = _extract_components_from_project_screens(list(screens))

    all_components: List[Dict[str, Any]] = []
    seen_ids = set()

    for comp in custom_registered + project_components:
        cid = str(comp.get("id")).lower()
        if cid not in seen_ids:
            seen_ids.add(cid)
            all_components.append(dict(comp))

    if req.include_presets is not False:
        for preset in DEFAULT_DESIGN_SYSTEM_COMPONENTS:
            cid = str(preset["id"]).lower()
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_components.append(dict(preset))

    cat_filter = (req.category or "").strip().lower()
    q_filter = (req.query or "").strip().lower()

    filtered: List[Dict[str, Any]] = []
    for comp in all_components:
        if cat_filter and str(comp.get("category", "")).lower() != cat_filter:
            continue
        if q_filter:
            haystack = " ".join([
                str(comp.get("id", "")),
                str(comp.get("name", "")),
                str(comp.get("category", "")),
                str(comp.get("description", "")),
                " ".join(str(s) for s in (comp.get("slots") or [])),
                str(comp.get("base_html", "")),
            ]).lower()
            if q_filter not in haystack:
                continue

        out_comp = dict(comp)
        if req.include_html is False:
            out_comp.pop("base_html", None)
        filtered.append(out_comp)

    categories_summary: Dict[str, int] = {}
    for c in filtered:
        cat = str(c.get("category") or "other")
        categories_summary[cat] = categories_summary.get(cat, 0) + 1

    return {
        "status": "success",
        "project_id": proj_id,
        "project_name": project_name,
        "total_components": len(filtered),
        "categories": categories_summary,
        "components": filtered,
    }


@router.post("/mcp/tools/compare_screens")
async def mcp_compare_screens(
    payload: MCPCompareScreensRequest,
    request: Request,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Compara estruturalmente (HTML/DOM/CSS/JS) e visualmente (pixel diff via Chromium) duas telas ou duas revisões da mesma tela."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos"
        )

    user = auth["user"]
    id_a = payload.screen_id_a or payload.screen_id
    if not id_a:
        raise HTTPException(
            status_code=400,
            detail="Informe 'screen_id' (para comparar revisões da mesma tela) ou 'screen_id_a' e 'screen_id_b'.",
        )
    id_b = payload.screen_id_b or id_a

    screen_a = await authorize_screen(id_a, user, "read", db)
    canvas_a_res = await db.execute(select(Canvas).where(Canvas.id == screen_a.canvas_id))
    canvas_a = canvas_a_res.scalars().first()
    if not canvas_a:
        raise HTTPException(status_code=404, detail="Canvas da tela A não encontrado")
    validate_mcp_project_access(auth, canvas_a.project_id)

    if id_b == id_a:
        screen_b = screen_a
        canvas_b = canvas_a
    else:
        screen_b = await authorize_screen(id_b, user, "read", db)
        canvas_b_res = await db.execute(select(Canvas).where(Canvas.id == screen_b.canvas_id))
        canvas_b = canvas_b_res.scalars().first()
        if not canvas_b:
            raise HTTPException(status_code=404, detail="Canvas da tela B não encontrado")
        validate_mcp_project_access(auth, canvas_b.project_id)

    rev_a_num = payload.revision_a
    rev_b_num = payload.revision_b

    # Se está comparando a mesma tela e nenhuma revisão foi especificada, compara (current_revision - 1) vs current_revision
    if id_a == id_b and rev_a_num is None and rev_b_num is None:
        rev_b_num = screen_b.current_revision
        rev_a_num = max(1, screen_a.current_revision - 1)

    async def _resolve_screen_version(scr: Screen, rev_num: Optional[int]) -> Dict[str, Any]:
        if rev_num is None or rev_num == scr.current_revision:
            return {
                "screen_id": scr.id,
                "screen_name": scr.name,
                "revision": scr.current_revision,
                "html": scr.html_content or "",
                "css": scr.css_content or "",
                "js": scr.js_content or "",
            }
        r_res = await db.execute(
            select(ScreenRevision).where(
                ScreenRevision.screen_id == scr.id,
                ScreenRevision.revision_number == rev_num,
            )
        )
        rev_obj = r_res.scalars().first()
        if not rev_obj:
            raise HTTPException(
                status_code=404,
                detail=f"Revisão {rev_num} não encontrada para a tela '{scr.name}' ({scr.id})",
            )
        return {
            "screen_id": scr.id,
            "screen_name": scr.name,
            "revision": rev_obj.revision_number,
            "html": rev_obj.html_content or "",
            "css": rev_obj.css_content or "",
            "js": rev_obj.js_content or "",
        }

    ver_a = await _resolve_screen_version(screen_a, rev_a_num)
    ver_b = await _resolve_screen_version(screen_b, rev_b_num)

    async def _get_project_tokens(pid: str) -> Dict[str, Any]:
        t_res = await db.execute(select(DesignTokens).where(DesignTokens.project_id == pid))
        t_row = t_res.scalars().first()
        if not t_row:
            return {}
        return {
            "light": t_row.light_tokens or {},
            "dark": t_row.dark_tokens or {},
            "shared": t_row.shared_tokens or {},
        }

    tokens_a = await _get_project_tokens(canvas_a.project_id)
    tokens_b = tokens_a if canvas_b.project_id == canvas_a.project_id else await _get_project_tokens(canvas_b.project_id)

    cmp_res = await compare_rendered_screens(
        html_a=ver_a["html"],
        html_b=ver_b["html"],
        css_a=ver_a["css"],
        css_b=ver_b["css"],
        js_a=ver_a["js"],
        js_b=ver_b["js"],
        tokens_a=tokens_a,
        tokens_b=tokens_b,
        viewport_name=payload.viewport or "desktop",
        theme=payload.theme or "light",
        full_page=bool(payload.full_page),
        include_visual_diff=payload.include_visual_diff is not False,
    )

    diff_bytes = cmp_res.pop("diff_screenshot_bytes", None)
    diff_url = None
    if diff_bytes:
        try:
            fn = save_asset(canvas_b.project_id, diff_bytes, "image/png")
            clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", screen_b.name or "screen")
            asset_obj = Asset(
                project_id=canvas_b.project_id,
                filename=fn,
                original_name=f"diff_{clean_name}_r{ver_a['revision']}_vs_r{ver_b['revision']}.png",
                content_type="image/png",
                size_bytes=len(diff_bytes),
            )
            db.add(asset_obj)
            await db.commit()
            await db.refresh(asset_obj)
            sig = generate_asset_signature(asset_obj.id)
            diff_url = build_public_url(request, f"/api/assets/{asset_obj.id}?sig={sig}")
        except Exception as asset_err:
            logger.warning(f"Falha ao persistir asset do diff visual: {asset_err}")

    diff_b64 = None
    if cmp_res.get("visual_diff"):
        diff_b64 = cmp_res["visual_diff"].get("diff_image_base64")
        cmp_res["visual_diff"]["diff_screenshot_url"] = diff_url

    return {
        "status": "success",
        "target_a": {
            "screen_id": ver_a["screen_id"],
            "screen_name": ver_a["screen_name"],
            "revision": ver_a["revision"],
        },
        "target_b": {
            "screen_id": ver_b["screen_id"],
            "screen_name": ver_b["screen_name"],
            "revision": ver_b["revision"],
        },
        "viewport": cmp_res["viewport"],
        "theme": cmp_res["theme"],
        "structural_diff": cmp_res["structural_diff"],
        "visual_diff": cmp_res["visual_diff"],
        "diff_screenshot_url": diff_url,
        "diff_image_base64": diff_b64,
    }


@router.post("/mcp/tools/list_screen_revisions")
async def mcp_list_screen_revisions(
    payload: MCPListScreenRevisionsRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lista todas as revisões do histórico de uma tela."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)
    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    limit = max(1, min(int(payload.limit or 30), 200))
    rev_res = await db.execute(
        select(ScreenRevision)
        .where(ScreenRevision.screen_id == screen.id)
        .order_by(ScreenRevision.revision_number.desc())
        .limit(limit)
    )
    revs = rev_res.scalars().all()

    return {
        "status": "success",
        "screen_id": screen.id,
        "screen_name": screen.name,
        "current_revision": screen.current_revision,
        "total_returned": len(revs),
        "revisions": [
            {
                "revision_number": r.revision_number,
                "actor": r.actor,
                "change_summary": r.change_summary,
                "html_length": len(r.html_content or ""),
                "css_length": len(r.css_content or ""),
                "js_length": len(r.js_content or ""),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in revs
        ],
    }


@router.post("/mcp/tools/get_canvas")
@router.post("/mcp/tools/list_canvases")
async def mcp_get_canvas(
    payload: Optional[MCPGetCanvasRequest] = None,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Retorna um canvas específico ou lista os canvases do projeto com suas telas ordenadas."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de projeto/canvas"
        )

    req = payload or MCPGetCanvasRequest()
    user = auth["user"]

    proj_id = get_effective_mcp_project_id(auth, req.project_id)
    if not proj_id and req.canvas_id:
        c_lookup = await db.execute(select(Canvas).where(Canvas.id == req.canvas_id))
        c_found = c_lookup.scalars().first()
        if not c_found:
            raise HTTPException(status_code=404, detail="Canvas não encontrado")
        proj_id = c_found.project_id

    if not proj_id:
        raise HTTPException(status_code=400, detail="project_id ou canvas_id é obrigatório")

    validate_mcp_project_access(auth, proj_id)
    project = await authorize_project(proj_id, user, "read", db)

    stmt = select(Canvas).where(Canvas.project_id == proj_id).order_by(Canvas.sort_order.asc(), Canvas.created_at.asc())
    if req.canvas_id:
        stmt = stmt.where(Canvas.id == req.canvas_id)

    canvases = (await db.execute(stmt)).scalars().all()
    if req.canvas_name:
        target_name = req.canvas_name.strip().lower()
        canvases = [c for c in canvases if target_name in (c.name or "").lower()]

    if (req.canvas_id or req.canvas_name) and not canvases:
        raise HTTPException(status_code=404, detail="Canvas solicitado não encontrado no projeto")

    canvases_out = []
    for c in canvases:
        s_res = await db.execute(
            select(Screen).where(Screen.canvas_id == c.id).order_by(Screen.created_at.asc())
        )
        screens = s_res.scalars().all()
        c_item: Dict[str, Any] = {
            "id": c.id,
            "name": c.name,
            "project_id": c.project_id,
            "sort_order": c.sort_order,
            "entry_screen_id": c.entry_screen_id,
            "screen_count": len(screens),
        }
        if req.include_screens is not False:
            c_item["screens"] = [
                {
                    "id": s.id,
                    "name": s.name,
                    "is_entry": s.is_entry,
                    "width": s.width,
                    "height": s.height,
                    "device_type": s.device_type,
                    "screen_kind": s.screen_kind,
                    "pos_x": s.pos_x,
                    "pos_y": s.pos_y,
                    "current_revision": s.current_revision,
                }
                for s in screens
            ]
        canvases_out.append(c_item)

    return {
        "status": "success",
        "project_id": project.id,
        "project_name": project.name,
        "total_canvases": len(canvases_out),
        "canvases": canvases_out,
    }


@router.post("/mcp/tools/upload_asset")
async def mcp_upload_asset(
    payload: MCPUploadAssetRequest,
    request: Request,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Faz upload de um novo asset (PNG, JPG, SVG, WEBP, GIF) em base64 para a biblioteca do projeto."""
    if "screen:write" not in auth["scopes"] and "project:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de escrita para enviar assets"
        )

    proj_id = get_effective_mcp_project_id(auth, payload.project_id)
    if not proj_id:
        raise HTTPException(status_code=400, detail="project_id é obrigatório")

    validate_mcp_project_access(auth, proj_id)
    user = auth["user"]
    await authorize_project(proj_id, user, "edit", db)

    raw_b64 = (payload.data_base64 or "").strip()
    content_type = (payload.content_type or "image/png").strip().lower()
    if raw_b64.startswith("data:") and "," in raw_b64:
        header, raw_b64 = raw_b64.split(",", 1)
        mime_match = re.match(r"data:([^;]+)", header, re.IGNORECASE)
        if mime_match:
            content_type = mime_match.group(1).strip().lower()

    try:
        raw_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Base64 inválido para o asset: {str(exc)}")

    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Conteúdo do asset está vazio")
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Tamanho do asset excede o limite de 10 MB")

    fn = save_asset(proj_id, raw_bytes, content_type)
    asset_obj = Asset(
        project_id=proj_id,
        uploaded_by=user.id,
        filename=fn,
        original_name=payload.filename.strip() or fn,
        content_type=content_type,
        size_bytes=len(raw_bytes),
    )
    db.add(asset_obj)
    await db.commit()
    await db.refresh(asset_obj)

    sig = generate_asset_signature(asset_obj.id)
    rel_url = f"/api/assets/{asset_obj.id}?sig={sig}"
    pub_url = build_public_url(request, rel_url)

    return {
        "status": "success",
        "asset": {
            "id": asset_obj.id,
            "project_id": asset_obj.project_id,
            "original_name": asset_obj.original_name,
            "content_type": asset_obj.content_type,
            "size_bytes": asset_obj.size_bytes,
            "url": rel_url,
            "public_url": pub_url,
            "created_at": asset_obj.created_at.isoformat() if asset_obj.created_at else None,
        },
    }


@router.post("/mcp/tools/get_screen_comments")
async def mcp_get_screen_comments(
    payload: MCPGetScreenCommentsRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lista os comentários e pins de revisão de uma tela."""
    if "project:read" not in auth["scopes"] and "screen:read" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de leitura de telas/projetos"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)
    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    stmt = select(Comment).where(Comment.screen_id == screen.id).order_by(Comment.created_at.asc())
    status_filter = (payload.status or "all").lower().strip()
    if status_filter in ("open", "resolved"):
        stmt = stmt.where(Comment.status == status_filter)

    comments = (await db.execute(stmt)).scalars().all()
    return {
        "status": "success",
        "screen_id": screen.id,
        "screen_name": screen.name,
        "total_comments": len(comments),
        "comments": [
            {
                "id": cm.id,
                "author_name": cm.author_name,
                "element_mb_id": cm.element_mb_id,
                "element_snippet": cm.element_snippet,
                "pin_x": cm.pin_x,
                "pin_y": cm.pin_y,
                "body": cm.body,
                "status": cm.status,
                "replies": cm.replies or [],
                "created_at": cm.created_at.isoformat() if cm.created_at else None,
                "resolved_at": cm.resolved_at.isoformat() if cm.resolved_at else None,
            }
            for cm in comments
        ],
    }


@router.post("/mcp/tools/add_comment")
async def mcp_add_comment(
    payload: MCPAddCommentRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Adiciona um novo comentário/anotação em uma tela ou responde e resolve um comentário existente."""
    if "screen:write" not in auth["scopes"] and "project:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo de escrita para adicionar comentários"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "read", db)
    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    key_name = auth["key"].name
    author = (payload.author_name or f"{user.name} (MCP: {key_name})").strip()

    if payload.resolve_comment_id:
        cm_res = await db.execute(
            select(Comment).where(
                Comment.id == payload.resolve_comment_id,
                Comment.screen_id == screen.id,
            )
        )
        existing_cm = cm_res.scalars().first()
        if not existing_cm:
            raise HTTPException(status_code=404, detail="Comentário a resolver não encontrado nesta tela")
        replies = list(existing_cm.replies or [])
        replies.append({
            "author_name": author,
            "body": payload.body.strip(),
            "created_at": utcnow().isoformat(),
        })
        existing_cm.replies = replies
        existing_cm.status = "resolved"
        existing_cm.resolved_at = utcnow()
        await db.commit()
        await db.refresh(existing_cm)
        return {
            "status": "success",
            "action": "resolved",
            "comment": {
                "id": existing_cm.id,
                "screen_id": existing_cm.screen_id,
                "author_name": existing_cm.author_name,
                "element_mb_id": existing_cm.element_mb_id,
                "body": existing_cm.body,
                "status": existing_cm.status,
                "replies": existing_cm.replies,
                "resolved_at": existing_cm.resolved_at.isoformat() if existing_cm.resolved_at else None,
            },
        }

    new_cm = Comment(
        screen_id=screen.id,
        author_id=user.id,
        author_name=author,
        element_mb_id=(payload.element_mb_id or "").strip(),
        element_snippet=(payload.element_snippet or "").strip(),
        pin_x=float(payload.pin_x if payload.pin_x is not None else 50.0),
        pin_y=float(payload.pin_y if payload.pin_y is not None else 50.0),
        body=payload.body.strip(),
        status="open",
        replies=[],
    )
    db.add(new_cm)
    await db.commit()
    await db.refresh(new_cm)

    return {
        "status": "success",
        "action": "created",
        "comment": {
            "id": new_cm.id,
            "screen_id": new_cm.screen_id,
            "author_name": new_cm.author_name,
            "element_mb_id": new_cm.element_mb_id,
            "pin_x": new_cm.pin_x,
            "pin_y": new_cm.pin_y,
            "body": new_cm.body,
            "status": new_cm.status,
            "created_at": new_cm.created_at.isoformat() if new_cm.created_at else None,
        },
    }


@router.post("/mcp/tools/rename_screen")
async def mcp_rename_screen(
    payload: MCPRenameScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Renomeia uma tela e/ou atualiza seus metadados estruturais sem tocar no HTML."""
    if "screen:write" not in auth["scopes"] and "project:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "edit", db)
    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    canvas = c_res.scalars().first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas não encontrado")
    validate_mcp_project_access(auth, canvas.project_id)

    old_name = screen.name
    if payload.new_name is not None and payload.new_name.strip():
        screen.name = payload.new_name.strip()
    if payload.width is not None and payload.width > 0:
        screen.width = int(payload.width)
    if payload.height is not None and payload.height > 0:
        screen.height = int(payload.height)
    if payload.device_type is not None:
        screen.device_type = payload.device_type.strip().lower()
    if payload.screen_kind is not None:
        screen.screen_kind = payload.screen_kind.strip().lower()
    if payload.pos_x is not None:
        screen.pos_x = int(payload.pos_x)
    if payload.pos_y is not None:
        screen.pos_y = int(payload.pos_y)
    if payload.transition is not None:
        screen.transition = payload.transition.strip().lower()

    if payload.is_entry is not None:
        screen.is_entry = bool(payload.is_entry)
        if screen.is_entry:
            p_res = await db.execute(select(Project).where(Project.id == canvas.project_id))
            proj = p_res.scalars().first()
            if proj:
                proj.entry_screen_id = screen.id

    await db.commit()
    await db.refresh(screen)

    return {
        "status": "success",
        "previous_name": old_name,
        "screen": {
            "id": screen.id,
            "name": screen.name,
            "canvas_id": screen.canvas_id,
            "project_id": canvas.project_id,
            "width": screen.width,
            "height": screen.height,
            "device_type": screen.device_type,
            "screen_kind": screen.screen_kind,
            "is_entry": screen.is_entry,
            "pos_x": screen.pos_x,
            "pos_y": screen.pos_y,
            "transition": screen.transition,
            "current_revision": screen.current_revision,
        },
    }


@router.post("/mcp/tools/move_screen_to_canvas")
async def mcp_move_screen_to_canvas(
    payload: MCPMoveScreenToCanvasRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Move uma tela para outro canvas do mesmo projeto (criando o canvas se necessário)."""
    if "screen:write" not in auth["scopes"] and "project:write" not in auth["scopes"]:
        raise HTTPException(
            status_code=403, detail="Chave MCP sem escopo 'screen:write'"
        )

    if not payload.target_canvas_id and not (payload.target_canvas_name and payload.target_canvas_name.strip()):
        raise HTTPException(
            status_code=400,
            detail="Informe 'target_canvas_id' ou 'target_canvas_name' para mover a tela.",
        )

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "edit", db)
    c_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
    source_canvas = c_res.scalars().first()
    if not source_canvas:
        raise HTTPException(status_code=404, detail="Canvas de origem não encontrado")
    project_id = source_canvas.project_id
    validate_mcp_project_access(auth, project_id)

    target_canvas: Optional[Canvas] = None
    created_new_canvas = False

    if payload.target_canvas_id:
        tc_res = await db.execute(
            select(Canvas).where(
                Canvas.id == payload.target_canvas_id,
                Canvas.project_id == project_id,
            )
        )
        target_canvas = tc_res.scalars().first()
        if not target_canvas:
            raise HTTPException(
                status_code=404,
                detail="Canvas de destino não encontrado neste projeto",
            )
    elif payload.target_canvas_name:
        clean_target_name = payload.target_canvas_name.strip()
        all_c_res = await db.execute(
            select(Canvas)
            .where(Canvas.project_id == project_id)
            .order_by(Canvas.sort_order.asc())
        )
        all_canvases = all_c_res.scalars().all()
        target_canvas = next(
            (c for c in all_canvases if (c.name or "").strip().lower() == clean_target_name.lower()),
            None,
        )
        if not target_canvas:
            if payload.create_if_missing is False:
                raise HTTPException(
                    status_code=404,
                    detail=f"Canvas '{clean_target_name}' não encontrado no projeto",
                )
            max_order = max((c.sort_order for c in all_canvases), default=-1)
            target_canvas = Canvas(
                project_id=project_id,
                name=clean_target_name,
                sort_order=max_order + 1,
            )
            db.add(target_canvas)
            await db.flush()
            created_new_canvas = True

    old_canvas_id = screen.canvas_id
    old_canvas_name = source_canvas.name
    screen.canvas_id = target_canvas.id
    await db.commit()
    await db.refresh(screen)

    return {
        "status": "success",
        "screen_id": screen.id,
        "screen_name": screen.name,
        "from_canvas": {"id": old_canvas_id, "name": old_canvas_name},
        "to_canvas": {
            "id": target_canvas.id,
            "name": target_canvas.name,
            "created": created_new_canvas,
        },
    }


@router.post("/mcp/tools/get_project_settings")
async def mcp_get_project_settings(
    payload: Optional[MCPGetProjectSettingsRequest] = None,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Lê e opcionalmente atualiza as configurações gerais do projeto (design_dials, entry_screen_id, descrição, visibilidade e contadores)."""
    req = payload or MCPGetProjectSettingsRequest()
    is_updating = any(
        v is not None
        for v in (
            req.update_name,
            req.update_description,
            req.update_design_dials,
            req.update_entry_screen_id,
        )
    )

    if is_updating:
        if "project:write" not in auth["scopes"] and "screen:write" not in auth["scopes"]:
            raise HTTPException(
                status_code=403, detail="Chave MCP sem escopo de escrita para atualizar configurações do projeto"
            )
    else:
        if "project:read" not in auth["scopes"]:
            raise HTTPException(
                status_code=403, detail="Chave MCP sem escopo 'project:read'"
            )

    proj_id = get_effective_mcp_project_id(auth, req.project_id)
    if not proj_id:
        raise HTTPException(status_code=400, detail="project_id é obrigatório")

    validate_mcp_project_access(auth, proj_id)
    user = auth["user"]
    project = await authorize_project(proj_id, user, "edit" if is_updating else "read", db)

    if req.update_name is not None and req.update_name.strip():
        project.name = req.update_name.strip()
    if req.update_description is not None:
        project.description = req.update_description.strip()
    if req.update_design_dials is not None and isinstance(req.update_design_dials, dict):
        dials = dict(project.design_dials or {"variance": 7, "motion": 4, "density": 4})
        dials.update(req.update_design_dials)
        project.design_dials = dials
    if req.update_entry_screen_id is not None:
        project.entry_screen_id = req.update_entry_screen_id.strip() or None

    if is_updating:
        await db.commit()
        await db.refresh(project)

    c_res = await db.execute(select(Canvas).where(Canvas.project_id == project.id))
    canvases = c_res.scalars().all()
    canvas_ids = [c.id for c in canvases]

    screens_count = 0
    if canvas_ids:
        s_res = await db.execute(select(Screen.id).where(Screen.canvas_id.in_(canvas_ids)))
        screens_count = len(s_res.all())

    a_res = await db.execute(select(Asset.id).where(Asset.project_id == project.id))
    assets_count = len(a_res.all())

    return {
        "status": "success",
        "updated": is_updating,
        "project": {
            "id": project.id,
            "workspace_id": project.workspace_id,
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "visibility": project.visibility,
            "design_dials": project.design_dials or {"variance": 7, "motion": 4, "density": 4},
            "entry_screen_id": project.entry_screen_id,
            "is_published": project.is_published,
            "is_archived": project.is_archived,
            "counts": {
                "canvases": len(canvases),
                "screens": screens_count,
                "assets": assets_count,
            },
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        },
    }


# ============================================================================
# Handler do Protocolo MCP JSON-RPC 2.0 Padrão (/mcp)
# ============================================================================


@router.post("/mcp")
async def mcp_jsonrpc_endpoint(
    request: Request,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Endpoint único compatível com JSON-RPC 2.0 para o protocolo MCP oficial (Claude Desktop, Cursor AI, Windsurf)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Corpo da requisição deve ser um JSON-RPC 2.0 válido",
        )

    method = body.get("method")
    msg_id = body.get("id")
    params = body.get("params", {})

    logger.info(f"[MCP-JSONRPC] Chamada recebida: method={method}, tool={params.get('name') if isinstance(params, dict) else None}")

    if msg_id is None or (
        method and (method.startswith("notifications/") or method == "initialized")
    ):
        return Response(status_code=204)

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mockbird-mcp-server", "version": "2.0.0"},
            },
        }

    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": MCP_TOOLS_SPEC}}

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        try:
            if tool_name == "list_projects":
                req_obj = MCPListProjectsRequest(**arguments) if arguments else None
                res = await mcp_list_projects(req_obj, auth, db)

            elif tool_name == "get_project_map":
                proj_id = get_effective_mcp_project_id(auth, arguments.get("project_id"))
                if not proj_id:
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": "project_id é obrigatório"},
                    }
                inc_tokens = arguments.get("include_tokens", True)
                sum_only = arguments.get("summary_only", False)
                res = await mcp_get_project_map(proj_id, inc_tokens, sum_only, auth, db)

            elif tool_name == "get_screen":
                req_obj = MCPGetScreenRequest(**arguments)
                res = await mcp_get_screen(req_obj, auth, db)

            elif tool_name == "create_screen":
                req_obj = MCPCreateScreenRequest(**arguments)
                res = await mcp_create_screen(req_obj, auth, db)

            elif tool_name == "duplicate_screen":
                req_obj = MCPDuplicateScreenRequest(**arguments)
                res = await mcp_duplicate_screen(req_obj, auth, db)

            elif tool_name == "delete_screen":
                req_obj = MCPDeleteScreenRequest(**arguments)
                res = await mcp_delete_screen(req_obj, auth, db)

            elif tool_name == "patch_screen_element":
                req_obj = MCPPatchRequest(**arguments)
                res = await mcp_patch_screen_element(req_obj, auth, db)

            elif tool_name == "update_screen_html":
                req_obj = MCPUpdateScreenHTMLRequest(**arguments)
                res = await mcp_update_screen_html(req_obj, auth, db)

            elif tool_name == "batch_update_screens":
                req_obj = MCPBatchUpdateScreensRequest(**arguments)
                res = await mcp_batch_update_screens(req_obj, auth, db)

            elif tool_name == "update_design_tokens":
                req_obj = MCPUpdateDesignTokensRequest(**arguments)
                res = await mcp_update_design_tokens(req_obj, auth, db)

            elif tool_name == "list_project_assets":
                req_obj = MCPListAssetsRequest(**arguments)
                res = await mcp_list_project_assets(req_obj, auth, db)

            elif tool_name == "list_scenarios":
                req_obj = MCPListScenariosRequest(**arguments)
                res = await mcp_list_scenarios(req_obj, auth, db)

            elif tool_name == "set_scenario_data":
                req_obj = MCPSetScenarioRequest(**arguments)
                res = await mcp_set_scenario_data(req_obj, auth, db)

            elif tool_name == "validate_screen_html":
                req_obj = MCPValidateHTMLRequest(**arguments)
                res = await mcp_validate_screen_html(req_obj, auth)

            elif tool_name == "get_implementation_bundle":
                s_id = arguments.get("screen_id")
                if not s_id:
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": "screen_id é obrigatório"},
                    }
                res = await mcp_get_implementation_bundle(s_id, auth, db)

            elif tool_name == "render_screen_screenshot":
                req_obj = MCPRenderScreenshotRequest(**arguments)
                res = await mcp_render_screen_screenshot(req_obj, request, auth, db)
                img_b64 = res.pop("image_base64", None)
                res.pop("screenshot_bytes", None)
                res.pop("image_data_uri", None)
                res_text = json.dumps(res, ensure_ascii=False, indent=2, default=str)
                content = [{"type": "text", "text": res_text}]
                if img_b64:
                    content.append({"type": "image", "data": img_b64, "mimeType": "image/png"})
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": content},
                }

            elif tool_name == "interact_screen_element":
                req_obj = MCPInteractElementRequest(**arguments)
                res = await mcp_interact_screen_element(req_obj, request, auth, db)
                img_b64 = res.pop("screenshot_base64", None)
                res.pop("screenshot_bytes", None)
                res.pop("image_data_uri", None)
                res_text = json.dumps(res, ensure_ascii=False, indent=2, default=str)
                content = [{"type": "text", "text": res_text}]
                if img_b64:
                    content.append({"type": "image", "data": img_b64, "mimeType": "image/png"})
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": content},
                }

            elif tool_name == "restore_screen_revision":
                req_obj = MCPRestoreScreenRevisionRequest(**arguments)
                res = await mcp_restore_screen_revision(req_obj, auth, db)

            elif tool_name == "render_screen_state":
                req_obj = MCPRenderScreenStateRequest(**arguments)
                res = await mcp_render_screen_state(req_obj, request, auth, db)
                img_b64 = res.pop("image_base64", None)
                res.pop("screenshot_bytes", None)
                res.pop("image_data_uri", None)
                res_text = json.dumps(res, ensure_ascii=False, indent=2, default=str)
                content = [{"type": "text", "text": res_text}]
                if img_b64:
                    content.append({"type": "image", "data": img_b64, "mimeType": "image/png"})
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": content},
                }

            elif tool_name == "diagnose_screen":
                req_obj = MCPDiagnoseScreenRequest(**arguments)
                res = await mcp_diagnose_screen(req_obj, auth, db)

            elif tool_name == "validate_screen":
                req_obj = MCPValidateScreenRequest(**arguments)
                res = await mcp_validate_screen(req_obj, auth, db)

            elif tool_name == "import_project_zip":
                req_obj = MCPImportProjectZipRequest(**arguments)
                res = await mcp_import_project_zip(req_obj, auth, db)

            elif tool_name == "search_screens":
                req_obj = MCPSearchScreensRequest(**arguments)
                res = await mcp_search_screens(req_obj, auth, db)

            elif tool_name in ("get_design_tokens", "export_tokens"):
                default_fmt = "all" if tool_name == "export_tokens" and "format" not in arguments else arguments.get("format", "json")
                req_obj = MCPGetDesignTokensRequest(**{**arguments, "format": default_fmt})
                res = await mcp_get_design_tokens(req_obj, auth, db)

            elif tool_name in ("get_component_library", "list_components"):
                req_obj = MCPGetComponentLibraryRequest(**arguments)
                res = await mcp_get_component_library(req_obj, auth, db)

            elif tool_name == "compare_screens":
                req_obj = MCPCompareScreensRequest(**arguments)
                res = await mcp_compare_screens(req_obj, request, auth, db)
                img_b64 = res.pop("diff_image_base64", None)
                if isinstance(res.get("visual_diff"), dict):
                    res["visual_diff"].pop("diff_image_base64", None)
                res_text = json.dumps(res, ensure_ascii=False, indent=2, default=str)
                content = [{"type": "text", "text": res_text}]
                if img_b64:
                    content.append({"type": "image", "data": img_b64, "mimeType": "image/png"})
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": content},
                }

            elif tool_name == "list_screen_revisions":
                req_obj = MCPListScreenRevisionsRequest(**arguments)
                res = await mcp_list_screen_revisions(req_obj, auth, db)

            elif tool_name in ("get_canvas", "list_canvases"):
                req_obj = MCPGetCanvasRequest(**arguments)
                res = await mcp_get_canvas(req_obj, auth, db)

            elif tool_name == "upload_asset":
                req_obj = MCPUploadAssetRequest(**arguments)
                res = await mcp_upload_asset(req_obj, request, auth, db)

            elif tool_name == "get_screen_comments":
                req_obj = MCPGetScreenCommentsRequest(**arguments)
                res = await mcp_get_screen_comments(req_obj, auth, db)

            elif tool_name == "add_comment":
                req_obj = MCPAddCommentRequest(**arguments)
                res = await mcp_add_comment(req_obj, auth, db)

            elif tool_name == "rename_screen":
                req_obj = MCPRenameScreenRequest(**arguments)
                res = await mcp_rename_screen(req_obj, auth, db)

            elif tool_name == "move_screen_to_canvas":
                req_obj = MCPMoveScreenToCanvasRequest(**arguments)
                res = await mcp_move_screen_to_canvas(req_obj, auth, db)

            elif tool_name == "get_project_settings":
                req_obj = MCPGetProjectSettingsRequest(**arguments)
                res = await mcp_get_project_settings(req_obj, auth, db)

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Ferramenta desconhecida '{tool_name}'",
                    },
                }

            res_text = json.dumps(res, ensure_ascii=False, indent=2, default=str)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": res_text}]},
            }

        except HTTPException as http_err:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32000,
                    "message": str(http_err.detail),
                    "data": {"status_code": http_err.status_code},
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"Erro interno ao executar ferramenta MCP: {str(exc)}",
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Método não suportado '{method}'"},
    }
