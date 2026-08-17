"""FastAPI 应用入口。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.agent import router as agent_router
from app.api.health import router as health_router
from app.api.interview import router as interview_router
from app.api.job import router as job_router
from app.api.match import router as match_router
from app.api.persistence import router as persistence_router
from app.api.profile import router as profile_router
from app.api.supervisor import router as supervisor_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.database import dispose_database
from app.memory.connection import dispose_redis
from app.storage.dependencies import dispose_resume_object_store
from app.vectorstore.dependencies import dispose_resume_knowledge_stores

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """记录应用生命周期事件，并为后续资源初始化预留统一入口。"""
    logger.info(
        "应用启动 name=%s environment=%s",
        settings.app_name,
        settings.environment,
    )
    try:
        yield
    finally:
        await dispose_database()
        await dispose_redis()
        await dispose_resume_object_store()
        await dispose_resume_knowledge_stores()
        logger.info("应用停止 name=%s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(health_router)
app.include_router(job_router)
app.include_router(profile_router)
app.include_router(match_router)
app.include_router(persistence_router)
app.include_router(agent_router)
app.include_router(interview_router)
app.include_router(supervisor_router)

# 前端作为独立静态目录存在，由同一个 FastAPI 进程托管，避免额外的 Node 运行要求。
frontend_directory = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/ui", StaticFiles(directory=frontend_directory, html=True), name="jobpilot-ui")


@app.get("/", include_in_schema=False)
async def open_jobpilot_ui() -> RedirectResponse:
    """访问根路径时进入 JobPilot Web 界面。"""
    return RedirectResponse(url="/ui/")
