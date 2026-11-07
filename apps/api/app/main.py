from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler
from app.db.session import SessionLocal, init_db
from app.services.accounts import ensure_default_user
from app.services.fees import seed_default_fee_rules

settings = get_settings()

# apps/api/app/main.py -> repo root = parents[3]
WEB_DIST = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"

app = FastAPI(title="IfBuy API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(AppError, app_error_handler)
app.include_router(router)


@app.middleware("http")
async def optional_token(request: Request, call_next):
    token = settings.ifbuy_token
    if token:
        auth = request.headers.get("Authorization", "")
        if request.url.path.startswith("/api/") and request.url.path != "/api/v1/health":
            if auth != f"Bearer {token}":
                from fastapi.responses import JSONResponse

                return JSONResponse(status_code=401, content={"code": "UNAUTHORIZED", "message": "需要登录令牌"})
    return await call_next(request)


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        ensure_default_user(db)
        seed_default_fee_rules(db)
    finally:
        db.close()


if WEB_DIST.is_dir() and (WEB_DIST / "index.html").exists():
    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            return {"detail": "Not Found"}
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
