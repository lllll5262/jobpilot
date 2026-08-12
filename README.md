# JobPilot

JobPilot 是一个分阶段构建的多 Agent 智能求职助手。阶段 5 使用 MySQL 持久化用户、Resume、Candidate Profile、JD 和岗位分析结果。

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
- 岗位匹配：`POST http://127.0.0.1:8000/matches/evaluate`
- 持久化工作流：见下方“数据库持久化”
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

## 岗位匹配

`POST /matches/evaluate` 的请求体同时包含 `resume`、`profile` 和 `job`。LLM 只负责项目相关度、经验匹配度和技能语义等价判断；Python Rule Engine 按以下固定规则计算最终分数：

- 必需技能匹配：40%
- 项目匹配：25%
- 经验匹配：15%
- 学历匹配：10%
- 优先技能加分：10%

推荐阈值为：80 分及以上 `RECOMMEND`，60～79 分 `CONSIDER`，低于 60 分 `NOT_RECOMMEND`。最终分数不接受 LLM 直接输入。

## 数据库持久化

复制 `.env.example` 后配置 `JOBPILOT_DATABASE_URL`，并将初始化脚本导入 MySQL：

```powershell
Get-Content "database/jobpilot_schema.sql" -Raw | mysql -h <mysql-host> -P <mysql-port> -u <mysql-user> -p
```

表初始化完成后，应用通过 SQLAlchemy 和 aiomysql 直接执行日常增删改查，不需要运行数据库迁移命令。

持久化接口：

- `POST /users`：创建用户
- `POST /users/{user_id}/resumes/parse`：解析并保存 Resume
- `POST /users/{user_id}/profiles/build`：构建并保存当前 Profile
- `GET /users/{user_id}/profile`：查看当前 Profile
- `POST /users/{user_id}/jobs/parse`：解析并保存 JD
- `GET /users/{user_id}/jobs`：查看历史 JD
- `POST /users/{user_id}/job-analyses`：匹配并保存分析
- `GET /users/{user_id}/job-analyses`：查看历史岗位分析

## 单 Job Agent

`POST /users/{user_id}/agents/job/analyze` 使用 LangGraph 驱动以下固定 Tool Calling 闭环：

```text
get_candidate_profile
  → parse_job_description
  → calculate_job_match
  → save_analysis
  → Final Answer
```

Tool 只负责读取可信 Agent State 并调用 Service；JD 解析、匹配规则和数据库读写仍分别位于 Service、Rule Engine 和 Repository。请求示例：

```json
{
  "message": "帮我分析一下这个岗位适不适合我。",
  "jd_text": "Java后端工程师，要求熟悉 Java、Spring Boot、MySQL 和 Redis。"
}
```

完整表结构与初始化说明见 [DATABASE.md](DATABASE.md)。

## 质量检查

```powershell
pytest
ruff check .
```

## 当前目录结构

```text
app/
├── agents/         # LangGraph Agent、状态和提示词
├── api/            # HTTP 路由
├── core/           # 配置、日志和异常处理
├── db/             # SQLAlchemy Async Engine 与 ORM Base
├── llm/            # OpenAI-compatible 客户端与 Prompt
├── models/         # SQLAlchemy ORM Model
├── parsers/        # PDF 等原始文档解析器
├── repository/     # 数据访问层
├── rules/          # 确定性的技能、学历和算分规则
├── schemas/        # Pydantic 数据模型
├── services/       # 应用服务
├── tools/          # Agent Tool 适配层，不承载业务逻辑
└── main.py         # 应用入口
tests/              # 自动化测试
```
