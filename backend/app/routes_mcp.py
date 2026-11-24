from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import hashlib
import json
import secrets
import re
from html.parser import HTMLParser

from app.database import get_db
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
)
from app.routes_auth import get_current_user, require_editor
from app.timeutils import utcnow
from app.authz import authorize_project, authorize_screen, get_effective_project_role
from app.jsx import html_to_jsx
from app.routes_assets import generate_asset_signature
from app.ws import broadcaster

router = APIRouter(tags=["mcp"])


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
        "description": "Retorna o mapa completo do projeto (canvases, telas, IDs, dimensões e tokens de design).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID do projeto Mockbird."}
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_screen",
        "description": "Retorna o código HTML, CSS, JS, dimensões, tokens e metadados completos de uma tela específica.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "screen_id": {"type": "string", "description": "ID da tela Mockbird."}
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
                        "current_revision": s.current_revision,
                    }
                    for s in screens
                ],
            }
        )

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "slug": project.slug,
            "visibility": project.visibility,
            "entry_screen_id": project.entry_screen_id,
        },
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
            "shared": tokens.shared_tokens if tokens else {},
        },
        "canvases": canvases_data,
    }


@router.post("/mcp/tools/get_screen")
async def mcp_get_screen(
    payload: MCPGetScreenRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db),
):
    """Retorna o código HTML, CSS, JS, dimensões e tokens completos de uma tela específica."""
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

    t_query = await db.execute(
        select(DesignTokens).where(DesignTokens.project_id == canvas.project_id)
    )
    tokens = t_query.scalars().first()

    return {
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
        "html_content": screen.html_content,
        "css_content": screen.css_content,
        "js_content": screen.js_content,
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {},
            "shared": tokens.shared_tokens if tokens else {},
        },
    }


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
                res = await mcp_get_project_map(proj_id, auth, db)

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
