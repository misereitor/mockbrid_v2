from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import hashlib
import secrets
import re

from app.database import get_db
from app.models import Project, Canvas, Screen, DesignTokens, Workspace, User, MCPApiKey, ScreenRevision
from app.routes_auth import get_current_user, require_editor
from app.authz import authorize_project, authorize_screen

router = APIRouter(tags=["mcp"])


def hash_mcp_key(raw_key: str) -> str:
    """Gera hash SHA-256 seguro da chave de API MCP para armazenamento no banco."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class MCPKeyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    project_id: Optional[str] = None
    scopes: Optional[List[str]] = ["project:read", "screen:write"]
    expires_in_days: Optional[int] = 90


class MCPKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    project_id: Optional[str]
    scopes: List[str]
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    created_at: datetime
    raw_key: Optional[str] = None

    class Config:
        from_attributes = True


class MCPPatchRequest(BaseModel):
    screen_id: str
    element_mb_id: str
    new_html_snippet: str
    change_summary: Optional[str] = "Alteração via MCP Agent"


# ============================================================================
# Autenticação Exclusiva de Chaves MCP
# ============================================================================

async def get_mcp_auth(request: Request, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Valida estritamente credenciais MCP via header 'Authorization: Bearer mb_live_...'.
    Rejeita terminantemente JWT de sessão para impedir escalada de privilégios."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial MCP ausente. Forneça o header 'Authorization: Bearer mb_live_...'."
        )

    token = auth_header.split(" ", 1)[1].strip()
    if not token.startswith("mb_live_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial MCP inválida. Tokens de sessão de usuário não são aceitos no servidor MCP. Crie uma chave de API específica para o MCP."
        )

    key_hash = hash_mcp_key(token)
    query = await db.execute(
        select(MCPApiKey, User)
        .join(User, User.id == MCPApiKey.user_id)
        .where(MCPApiKey.key_hash == key_hash)
    )
    row = query.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave MCP inválida ou não encontrada")

    mcp_key, user = row[0], row[1]

    if mcp_key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave MCP revogada")

    if mcp_key.expires_at and mcp_key.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave MCP expirada")

    # Atualiza timestamp de último uso
    mcp_key.last_used_at = datetime.utcnow()
    await db.commit()

    return {
        "key": mcp_key,
        "user": user,
        "project_id": mcp_key.project_id,
        "scopes": mcp_key.scopes or []
    }


# ============================================================================
# Endpoints de Gestão de Chaves MCP (Painel do Usuário / Frontend)
# ============================================================================

@router.get("/api/mcp/keys", response_model=List[MCPKeyOut])
async def list_mcp_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lista as chaves MCP ativas da organização criadas pelo usuário."""
    query = await db.execute(
        select(MCPApiKey)
        .where(
            MCPApiKey.organization_id == current_user.organization_id,
            MCPApiKey.user_id == current_user.id
        )
        .order_by(MCPApiKey.created_at.desc())
    )
    keys = query.scalars().all()
    return [MCPKeyOut.model_validate(k) for k in keys]


@router.post("/api/mcp/keys", response_model=MCPKeyOut)
async def create_mcp_key(
    payload: MCPKeyCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Gera uma nova chave de API para conexão de agentes MCP.
    A chave em texto claro é retornada uma única vez no campo 'raw_key'."""
    # Se vinculada a um projeto específico, valida permissão
    if payload.project_id:
        await authorize_project(payload.project_id, current_user, "read", db)

    random_secret = secrets.token_hex(24)
    raw_key = f"mb_live_{random_secret}"
    prefix = f"mb_live_{random_secret[:6]}..."
    key_hash = hash_mcp_key(raw_key)

    expires_at = datetime.utcnow() + timedelta(days=payload.expires_in_days or 90)

    mcp_key = MCPApiKey(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        project_id=payload.project_id,
        name=payload.name.strip(),
        prefix=prefix,
        key_hash=key_hash,
        scopes=payload.scopes or ["project:read"],
        expires_at=expires_at
    )
    db.add(mcp_key)
    await db.commit()
    await db.refresh(mcp_key)

    out = MCPKeyOut.model_validate(mcp_key)
    out.raw_key = raw_key
    return out


@router.delete("/api/mcp/keys/{key_id}")
async def revoke_mcp_key(
    key_id: str,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db)
):
    """Revoga imediatamente uma chave MCP."""
    query = await db.execute(
        select(MCPApiKey).where(
            MCPApiKey.id == key_id,
            MCPApiKey.organization_id == current_user.organization_id
        )
    )
    mcp_key = query.scalars().first()
    if not mcp_key:
        raise HTTPException(status_code=404, detail="Chave MCP não encontrada")

    mcp_key.revoked_at = datetime.utcnow()
    await db.commit()
    return {"message": "Chave MCP revogada com sucesso", "key_id": key_id}


# ============================================================================
# Endpoints do Protocolo MCP (/mcp)
# ============================================================================

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
        "tools": [
            {
                "name": "get_project_map",
                "description": "Retorna o mapa completo do projeto (canvases, telas, tokens de design)."
            },
            {
                "name": "patch_screen_element",
                "description": "Atualiza cirurgicamente um elemento específico de uma tela via data-mb-id."
            },
            {
                "name": "get_implementation_bundle",
                "description": "Retorna o pacote de código React JSX pronto para produção."
            }
        ]
    }


@router.post("/mcp/tools/get_project_map")
async def mcp_get_project_map(
    project_id: str,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db)
):
    """Retorna mapa de projeto (canvases, telas, tokens) com escopo e tenant verificados."""
    if "project:read" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo 'project:read'")

    # Se a chave for restrita a um projeto, não permite ler outro
    if auth["project_id"] and auth["project_id"] != project_id:
        raise HTTPException(status_code=403, detail="Esta chave MCP está restrita a outro projeto")

    user = auth["user"]
    project = await authorize_project(project_id, user, "read", db)

    # Tokens
    t_query = await db.execute(select(DesignTokens).where(DesignTokens.project_id == project_id))
    tokens = t_query.scalars().first()

    # Canvases e Telas
    c_query = await db.execute(select(Canvas).where(Canvas.project_id == project_id).order_by(Canvas.sort_order.asc()))
    canvases = c_query.scalars().all()

    canvases_data = []
    for c in canvases:
        s_query = await db.execute(select(Screen).where(Screen.canvas_id == c.id).order_by(Screen.created_at.asc()))
        screens = s_query.scalars().all()
        canvases_data.append({
            "id": c.id,
            "name": c.name,
            "screens": [
                {
                    "id": s.id,
                    "name": s.name,
                    "is_entry": s.is_entry,
                    "width": s.width,
                    "height": s.height
                } for s in screens
            ]
        })

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "slug": project.slug,
            "visibility": project.visibility,
            "entry_screen_id": project.entry_screen_id
        },
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {}
        },
        "canvases": canvases_data
    }


@router.post("/mcp/tools/patch_screen_element")
async def mcp_patch_screen_element(
    payload: MCPPatchRequest,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db)
):
    """Aplica uma modificação cirúrgica em um elemento específico da tela via data-mb-id."""
    if "screen:write" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo 'screen:write'")

    user = auth["user"]
    screen = await authorize_screen(payload.screen_id, user, "edit", db)

    # Se a chave estiver restrita a um projeto, valida compatibilidade
    if auth["project_id"]:
        canvas_res = await db.execute(select(Canvas).where(Canvas.id == screen.canvas_id))
        canvas = canvas_res.scalars().first()
        if not canvas or canvas.project_id != auth["project_id"]:
            raise HTTPException(status_code=403, detail="Esta chave MCP está restrita a outro projeto")

    clean_id = payload.element_mb_id.lstrip('#').strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Identificador do elemento (data-mb-id) é obrigatório")

    pattern = rf'(<([a-zA-Z0-9\-]+)[^>]*(?:data-mb-id|id)=["\']{re.escape(clean_id)}["\'][\s\S]*?</\2>)'
    if not re.search(pattern, screen.html_content, re.IGNORECASE):
        self_pattern = rf'(<([a-zA-Z0-9\-]+)[^>]*(?:data-mb-id|id)=["\']{re.escape(clean_id)}["\'][^>]*\/?>)'
        if not re.search(self_pattern, screen.html_content, re.IGNORECASE):
            raise HTTPException(
                status_code=404,
                detail=f"Elemento com data-mb-id '{clean_id}' não encontrado no HTML da tela."
            )
        new_html = re.sub(self_pattern, payload.new_html_snippet.strip(), screen.html_content, count=1, flags=re.IGNORECASE)
    else:
        new_html = re.sub(pattern, payload.new_html_snippet.strip(), screen.html_content, count=1, flags=re.IGNORECASE)

    screen.html_content = new_html
    screen.current_revision += 1

    # Registra snapshot de revisão com autoria explícita da chave MCP
    key_name = auth["key"].name
    rev = ScreenRevision(
        screen_id=screen.id,
        revision_number=screen.current_revision,
        html_content=screen.html_content,
        css_content=screen.css_content,
        js_content=screen.js_content,
        actor=f"mcp:{key_name}",
        change_summary=payload.change_summary or "Patch cirúrgico via MCP Agent"
    )
    db.add(rev)
    await db.commit()
    await db.refresh(screen)

    return {
        "status": "success",
        "screen_id": screen.id,
        "revision": screen.current_revision,
        "applied_snippet": payload.new_html_snippet[:150],
        "actor": f"mcp:{key_name}"
    }


@router.post("/mcp/tools/get_implementation_bundle")
async def mcp_get_implementation_bundle(
    screen_id: str,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db)
):
    """Devolve pacote pronto para desenvolvedores (JSX React sanitizado + Tokens)."""
    if "project:read" not in auth["scopes"] and "export:read" not in auth["scopes"]:
        raise HTTPException(status_code=403, detail="Chave MCP sem escopo de leitura/exportação")

    user = auth["user"]
    screen = await authorize_screen(screen_id, user, "read", db)

    # Sanitiza o nome do componente para identificador React válido
    safe_name = re.sub(r'[^a-zA-Z0-9]+', '', "".join(w.capitalize() for w in screen.name.split())) or "Screen"
    clean_html = screen.html_content.replace('class="', 'className="')
    jsx_component = (
        f"export function {safe_name}Component() {{\n"
        f"  return (\n"
        f"    {clean_html}\n"
        f"  );\n"
        f"}}"
    )

    return {
        "screen_id": screen.id,
        "screen_name": screen.name,
        "html": screen.html_content,
        "css": screen.css_content,
        "react_jsx": jsx_component
    }


# ============================================================================
# Handler do Protocolo MCP JSON-RPC 2.0 Padrão (/mcp)
# ============================================================================

@router.post("/mcp")
async def mcp_jsonrpc_endpoint(
    request: Request,
    auth: Dict[str, Any] = Depends(get_mcp_auth),
    db: AsyncSession = Depends(get_db)
):
    """Endpoint único compatível com JSON-RPC 2.0 para o protocolo MCP oficial."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corpo da requisição deve ser um JSON-RPC 2.0 válido")

    method = body.get("method")
    msg_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "mockbird-mcp-server",
                    "version": "2.0.0"
                }
            }
        }

    elif method == "tools/list":
        tools = [
            {
                "name": "get_project_map",
                "description": "Retorna a estrutura completa do projeto (telas, canvases e design tokens).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "ID do projeto Mockbird"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "patch_screen_element",
                "description": "Modifica cirurgicamente um elemento de tela pelo data-mb-id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "screen_id": {"type": "string"},
                        "element_mb_id": {"type": "string"},
                        "new_html_snippet": {"type": "string"},
                        "change_summary": {"type": "string"}
                    },
                    "required": ["screen_id", "element_mb_id", "new_html_snippet"]
                }
            },
            {
                "name": "get_implementation_bundle",
                "description": "Obtém código React JSX pronto para produção.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "screen_id": {"type": "string"}
                    },
                    "required": ["screen_id"]
                }
            }
        ]
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": tools}
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "get_project_map":
            proj_id = arguments.get("project_id") or auth["project_id"]
            if not proj_id:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": "project_id é obrigatório"}
                }
            res = await mcp_get_project_map(proj_id, auth, db)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": str(res)}]}}

        elif tool_name == "patch_screen_element":
            payload = MCPPatchRequest(**arguments)
            res = await mcp_patch_screen_element(payload, auth, db)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": str(res)}]}}

        elif tool_name == "get_implementation_bundle":
            s_id = arguments.get("screen_id")
            res = await mcp_get_implementation_bundle(s_id, auth, db)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": str(res)}]}}

        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Ferramenta desconhecida '{tool_name}'"}
            }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Método não suportado '{method}'"}
    }
