"""JobPilot 前端静态资源和入口测试。"""

import asyncio

import httpx

from app.main import app


async def request(path: str, *, follow_redirects: bool = False) -> httpx.Response:
    """通过 ASGI 读取前端资源，不启动真实端口。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=follow_redirects,
    ) as client:
        return await client.get(path)


def test_root_redirects_to_jobpilot_ui() -> None:
    """根路径应跳转到 Web 应用，而不是返回 404。"""
    response = asyncio.run(request("/"))
    assert response.status_code == 307
    assert response.headers["location"] == "/ui/"


def test_frontend_assets_are_served() -> None:
    """HTML、样式和交互脚本都应由 FastAPI 正常托管。"""
    html = asyncio.run(request("/ui/"))
    css = asyncio.run(request("/ui/styles.css"))
    script = asyncio.run(request("/ui/app.js"))

    assert html.status_code == 200
    assert "JobPilot AI 求职助手" in html.text
    assert 'id="resume-file"' in html.text
    assert 'id="optimization-modal"' in html.text
    assert "/users/${state.context.userId}/supervisor" in script.text
    assert "/users/${state.context.userId}/resumes/parse" in script.text
    assert "/users/${state.context.userId}/profiles/build" in script.text
    assert "/users/${state.context.userId}/jobs?limit=50&offset=0" in script.text
    assert 'action === "optimize_resume"' in script.text
    assert 'data-conversation-id="${escapeHtml(conversation.id)}"' in script.text
    assert "openConversation(button.dataset.conversationId)" in script.text
    assert 'localStorage.setItem(CONVERSATION_STORAGE_KEY' in script.text
    assert ".content-grid" in css.text
