# JobPilot

JobPilot 是一个分阶段构建的多 Agent 智能求职助手。阶段 3 在简历解析基础上新增独立的候选人能力画像。

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
- JD 解析：`POST http://127.0.0.1:8000/jobs/parse`
- 简历解析：`POST http://127.0.0.1:8000/resumes/parse`
- 能力画像：`POST http://127.0.0.1:8000/profiles/build`
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

JD 解析支持 Qwen 和 DeepSeek 的 OpenAI-compatible API。默认配置为 Qwen；如需切换 DeepSeek，请参考 `.env.example` 修改供应商、API 地址和模型。API Key 只应保存在本地 `.env` 或系统环境变量中，禁止提交到 Git。

## JD 解析

请求示例：

```powershell
$body = @{
  jd_text = "Java后端实习生，熟悉 Java、Spring Boot、MySQL，掌握 Redis，Kafka 经验优先。"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/jobs/parse" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

响应中的 `data` 已经过 Pydantic Schema 校验；模型返回非法 JSON、缺少字段或包含额外字段时，接口会返回统一错误结构。

## 简历解析

上传字段名为 `file`，当前只支持带有文本层的 PDF，不支持图片扫描件和 OCR。可在 Swagger 文档中直接上传，也可以使用：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/resumes/parse" `
  -H "accept: application/json" `
  -F "file=@E:/path/to/resume.pdf;type=application/pdf"
```

默认限制为 10 MB、20 页和 50000 个提取字符，可通过 `.env` 中的 `JOBPILOT_RESUME_*` 配置调整。

## 候选人能力画像

Resume 保存候选人做过的教育、项目和实习经历；Candidate Profile 根据这些经历评估技能熟练度和领域能力。两者使用独立 Schema，`POST /profiles/build` 接收已解析的 Resume：

```json
{
  "resume": {
    "personal_info": {"name": null, "email": null, "phone": null, "location": null},
    "education": [],
    "skills": ["Java", "Redis", "RabbitMQ"],
    "projects": [],
    "internships": [],
    "certificates": []
  }
}
```

技能等级仅允许 `advanced`、`intermediate`、`beginner` 和 `unknown`。当前阶段不保存数据库，调用方负责保留 Resume 和 Profile。

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
├── llm/            # OpenAI-compatible 客户端与 Prompt
├── parsers/        # PDF 等原始文档解析器
├── schemas/        # Pydantic 数据模型
├── services/       # 应用服务
└── main.py         # 应用入口
tests/              # 自动化测试
```
