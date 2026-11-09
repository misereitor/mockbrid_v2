from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.config import settings
from app.database import engine, Base
from app.routes_auth import router as auth_router
from app.routes_projects import router as projects_router
from app.routes_screens import router as screens_router
from app.routes_tokens import router as tokens_router
from app.routes_comments import router as comments_router
from app.routes_mcp import router as mcp_router
from app.routes_org import router as org_router
from app.routes_public import router as public_router
from app.routes_ai import router as ai_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(screens_router)
app.include_router(tokens_router)
app.include_router(comments_router)
app.include_router(mcp_router)
app.include_router(org_router)
app.include_router(public_router)
app.include_router(ai_router)


@app.get("/api/health")
async def health_check():
    db_status = "connected"
    try:
        from sqlalchemy import text
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "database": db_status
    }


FRONTEND_DIST = "/app/frontend_dist"

if os.path.exists(FRONTEND_DIST):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("mcp/"):
            raise HTTPException(
                status_code=404, detail="Endpoint de API não encontrado"
            )
        index_file = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"error": "Frontend build não encontrado"}
