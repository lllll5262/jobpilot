"""健康检查接口测试。"""

import asyncio

import httpx

from app.main import app


async def _get(path: str) -> httpx.Response:
    """通过 ASGI 传输层请求应用，无需启动真实网络端口。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get(path)


def test_health_check_returns_ok() -> None:
    """服务正常时应返回约定的统一响应结构。"""
    response = asyncio.run(_get("/health"))

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {"status": "ok"},
    }


def test_unknown_route_uses_common_response() -> None:
    """不存在的路由也应由全局异常处理器转换为统一结构。"""
    response = asyncio.run(_get("/missing"))

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "Not Found",
        "data": None,
    }
