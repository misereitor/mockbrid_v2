from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any, List

from app.database import get_db
from app.models import Project, Canvas, Screen, DesignTokens, Comment, Workspace, User
from app.routes_auth import get_current_user

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/info")
async def mcp_server_info():
    """Handshake com instruções automáticas de design para IAs externas (Taste / Emil / Craft)."""
    return {
        "name": "mockbird-mcp-server",
        "version": "2.0.0",
        "instructions": (
            "Você é o agente de design do Mockbird v2. "
            "Regras de Ouro: (1) Use sempre as variáveis de Design Tokens (--color-primary, --color-bg, etc.) em vez de cores hardcoded. "
            "(2) Siga a filosofia do Emil Kowalski: animações suaves (<300ms ease-out), sem motion desnecessário. "
            "(3) Priorize contrastes acessíveis e telas responsivas. "
            "(4) Sempre que criar ou editar elementos, defina o atributo data-mb-id exclusivo."
        ),
        "tools": [
            {
                "name": "get_project_map",
                "description": "Retorna o mapa completo do projeto (canvases, telas, tokens de design e comentários pendentes)."
            },
            {
                "name": "patch_screen_element",
                "description": "Atualiza cirurgicamente um elemento específico de uma tela via data-mb-id."
            },
            {
                "name": "get_implementation_bundle",
                "description": "Retorna o pacote de código (HTML limpo, Tokens CSS e React JSX) pronto para programar o sistema de produção."
            }
        ]
    }


@router.post("/tools/get_project_map")
async def mcp_get_project_map(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Busca projeto garantindo tenant isolation
    p_query = await db.execute(
        select(Project)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(
            Project.id == project_id,
            Workspace.organization_id == current_user.organization_id
        )
    )
    project = p_query.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Tokens
    t_query = await db.execute(select(DesignTokens).where(DesignTokens.project_id == project_id))
    tokens = t_query.scalars().first()

    # Canvases e Telas
    c_query = await db.execute(select(Canvas).where(Canvas.project_id == project_id))
    canvases = c_query.scalars().all()

    canvases_data = []
    for c in canvases:
        s_query = await db.execute(select(Screen).where(Screen.canvas_id == c.id))
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
            "entry_screen_id": project.entry_screen_id
        },
        "tokens": {
            "light": tokens.light_tokens if tokens else {},
            "dark": tokens.dark_tokens if tokens else {}
        },
        "canvases": canvases_data
    }


@router.post("/tools/get_implementation_bundle")
async def mcp_get_implementation_bundle(
    screen_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    s_query = await db.execute(
        select(Screen)
        .join(Canvas, Canvas.id == Screen.canvas_id)
        .join(Project, Project.id == Canvas.project_id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(
            Screen.id == screen_id,
            Workspace.organization_id == current_user.organization_id
        )
    )
    screen = s_query.scalars().first()
    if not screen:
        raise HTTPException(status_code=404, detail="Tela não encontrada")

    # Gera JSX React limpo
    clean_html = screen.html_content.replace('class="', 'className="')
    jsx_component = (
        f"export function {screen.name.replace(' ', '')}Screen() {{\n"
        f"  return (\n"
        f"    {clean_html}\n"
        f"  );\n"
        f"}}"
    )

    return {
        "screen_name": screen.name,
        "html": screen.html_content,
        "css": screen.css_content,
        "react_jsx": jsx_component
    }

