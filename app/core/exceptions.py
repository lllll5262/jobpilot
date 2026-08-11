"""全局异常类型与处理器。"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ApiResponse

logger = logging.getLogger(__name__)


class AppException(Exception):
    """业务异常基类，后续阶段的领域异常可复用该返回协议。"""

    def __init__(
        self,
        message: str,
        *,
        code: int = 400,
        status_code: int = 400,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.data = data


def _error_response(*, status_code: int, code: int, message: str, data: Any = None) -> JSONResponse:
    """将不同来源的异常转换为同一种响应结构。"""
    body = ApiResponse[Any](code=code, message=message, data=data)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body.model_dump()),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """为 FastAPI 应用注册统一异常处理器。"""

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "业务异常 method=%s path=%s code=%s message=%s",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
        )
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            data=exc.data,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            "请求参数校验失败 method=%s path=%s",
            request.method,
            request.url.path,
        )
        return _error_response(
            status_code=422,
            code=422,
            message="validation error",
            data={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        logger.warning(
            "HTTP 异常 method=%s path=%s status_code=%s",
            request.method,
            request.url.path,
            exc.status_code,
        )
        message = exc.detail if isinstance(exc.detail, str) else "http error"
        return _error_response(
            status_code=exc.status_code,
            code=exc.status_code,
            message=message,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        # 未知异常仅记录在服务端，避免向调用方泄露内部实现细节。
        logger.exception(
            "未处理异常 method=%s path=%s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return _error_response(
            status_code=500,
            code=500,
            message="internal server error",
        )
