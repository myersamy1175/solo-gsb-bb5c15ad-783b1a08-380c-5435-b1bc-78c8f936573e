"""FastAPI 应用入口：建库、同步规则图、写入种子、挂载 API 与静态界面。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import WEB_DIR
from .database import SessionLocal, init_db
from .routers import plans, reagents, rule_versions, rules, runs
from .rules_store import sync_builtin_rules
from .seed import seed_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        sync_builtin_rules(db)
        seed_data(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="实验室配液相容性推演台",
    description="录入试剂属性与按时间排列的加液步骤，基于可维护规则图逐步推演相容性。",
    version="1.2.0",
    lifespan=lifespan,
)

app.include_router(reagents.router)
app.include_router(plans.router)
app.include_router(rule_versions.router)
app.include_router(rules.router)
app.include_router(runs.router)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


# 静态网页（API 路由已先注册，不会被覆盖）
if Path(WEB_DIR).exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")
