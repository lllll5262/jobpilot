"""FastAPI 应用入口。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.agent import router as agent_router
from app.api.health import router as health_router
from app.api.job import router as job_router
from app.api.match import router as match_router
from app.api.persistence import router as persistence_router
from app.api.profile import router as profile_router
from app.api.resume import router as resume_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.database import dispose_database

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
    yield
    await dispose_database()
    logger.info("应用停止 name=%s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(health_router)
app.include_router(job_router)
app.include_router(resume_router)
app.include_router(profile_router)
app.include_router(match_router)
app.include_router(persistence_router)
app.include_router(agent_router)
