# JobPilot

JobPilot 是一个分阶段构建的多 Agent 智能求职助手。阶段 0 仅提供可独立运行、测试和提交的 FastAPI 基础工程，不包含 AI 能力。

## 环境要求

- Python 3.11+
- Git

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

服务启动后可访问：

- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`

健康检查响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "ok"
  }
}
```

## 配置

应用通过 `pydantic-settings` 读取环境变量。复制 `.env.example` 为 `.env`，然后按需修改；环境变量以 `JOBPILOT_` 为前缀，系统环境变量的优先级高于 `.env`。

## 质量检查

```powershell
pytest
ruff check .
```

## 当前目录结构

```text
app/
├── api/            # HTTP 路由
├── core/           # 配置、日志和异常处理
├── schemas/        # Pydantic 数据模型
└── main.py         # 应用入口
tests/              # 自动化测试
```
