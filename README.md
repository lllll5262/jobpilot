# JobPilot

JobPilot 是一个分阶段构建的多 Agent 智能求职助手。MySQL 保存业务关系和简历对象元数据，MinIO 保存原始 PDF，Milvus 保存可检索的简历父子块向量。

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
- 简历上传：`POST http://127.0.0.1:8000/users/{user_id}/resumes/parse`
- 简历异步上传：`POST http://127.0.0.1:8000/users/{user_id}/resumes/parse-async`
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
curl.exe -X POST "http://127.0.0.1:8000/users/1/resumes/parse" `
  -H "accept: application/json" `
  -F "file=@E:/path/to/resume.pdf;type=application/pdf"
```

默认限制为 10 MB、20 页和 50000 个提取字符，可通过 `.env` 中的 `JOBPILOT_RESUME_*` 配置调整。

持久化上传接口 `POST /users/{user_id}/resumes/parse` 还会执行以下流程：

```text
PDF → SHA-256 → MySQL 按 (user_id, doc_hash) 去重
 ├→ 已存在：直接返回已有 Resume，不重复解析和向量化
 └→ 新文件 ───────────────────────────────────────→ MinIO 私有对象
      ├→ 文件哈希、大小、Content-Type、s3:// 地址 ─→ MySQL
      └→ 清洗正文 → 父块 1000 字符 → 子块 400 字符
                                      └→ BGE-M3 稠密/稀疏向量 → Milvus
```

生产入库可使用 `POST /users/{user_id}/resumes/parse-async`。接口完成文件校验、
SHA-256 预去重和 MinIO 暂存后立即返回任务 ID；Celery 消息只包含用户 ID、哈希和
MinIO 对象元数据，不包含 PDF 二进制。Worker 再执行 PDF 解析、MySQL 唯一约束去重、
分块、批量 Embedding 和 Milvus 写入。查询任务状态：

```text
GET /users/{user_id}/resumes/ingestions/{task_id}
```

同步或异步提交命中重复文件时，响应会返回 `message="简历已上传过"`、
`duplicate=true` 和已有 Resume。Web 前端会显示“这份简历已经上传过了”，并跳过
Profile 重建、MinIO 重复保存和 Milvus 重复向量化。

启动 Worker（BGE-M3 模型占用内存较大，建议每个 Worker 进程并发为 1）：

```powershell
celery -A app.tasks.celery_app:celery_app worker --loglevel=INFO --concurrency=1
```

`JOBPILOT_CELERY_BROKER_URL` 与 `JOBPILOT_CELERY_RESULT_BACKEND` 必须指向 API 和
Worker 都能访问的服务。示例默认使用 Redis 的独立 DB；也可把 Broker 改为 RabbitMQ，
结果后端仍建议使用 Redis，便于 HTTP 状态接口跨进程查询结果。

Milvus 使用稠密向量和稀疏向量双路召回，并通过 `WeightedRanker(0.7, 0.3)`
融合排序，不依赖 Elasticsearch。`POST /users/{user_id}/resumes/search` 用于检索相关
子块并返回对应父块。Milvus 实体自身保存 `parent_content`，用于生成上下文和来源核验；
`GET /users/{user_id}/resumes/{resume_id}/source` 从 MySQL 读取对象元数据，并为
MinIO 私有对象生成短时下载 URL。MySQL 中的 Resume ID 继续作为 Profile 和 Interview
的外键。

Milvus 新环境会创建版本化物理 Collection（默认 `jobpilot_resume_chunks_v1`），应用
始终通过 Alias（默认 `jobpilot_resume_chunks_current`）读写。旧环境若已存在
`jobpilot_resume_chunks`，首次启动只会把 Alias 指向旧 Collection，不迁移、不删除数据；
因此现有 `resume_id=6` 的向量仍可检索。后续升级应先离线构建并校验新的物理
Collection，再使用 Milvus `alter_alias` 原子切换；应用启动不会自动把 Alias 切到空版本。
单次 Embedding 和 insert 的块数由 `JOBPILOT_RESUME_EMBEDDING_BATCH_SIZE` 控制。

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

复制 `.env.example` 后配置 `JOBPILOT_DATABASE_URL`、`JOBPILOT_MINIO_*` 和
`JOBPILOT_MILVUS_*`。新数据库可直接导入初始化脚本：

```powershell
Get-Content "database/jobpilot_schema.sql" -Raw | mysql -h <mysql-host> -P <mysql-port> -u <mysql-user> -p
```

已有 `resumes` 表需要先备份数据库，再执行
`database/migrate_resume_minio_metadata.sql` 增加对象元数据列。旧简历没有对应的原始
PDF 对象，需重新上传后才能获得下载地址。

持久化接口：

- `POST /users`：创建用户
- `POST /users/{user_id}/resumes/parse`：解析并保存 Resume
- `POST /users/{user_id}/resumes/parse-async`：暂存 PDF 并提交 Celery 入库任务
- `GET /users/{user_id}/resumes/ingestions/{task_id}`：查询异步入库状态和结果
- `POST /users/{user_id}/resumes/search`：Milvus 稠密/稀疏混合检索
- `GET /users/{user_id}/resumes/{resume_id}/source`：返回 MinIO 元数据和短时下载地址
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

## 多轮会话与 Redis Memory

阶段 7 新增 `POST /users/{user_id}/agents/job/chat`。同一个 `session_id` 会读取最近 N 轮对话与最近岗位分析缓存，因此可以继续追问“刚才那个岗位”。该兼容接口不再单独保存 Job Agent Checkpoint；统一前端会话只由 Supervisor 保存 LangGraph Checkpoint。首次分析请求：

```json
{
  "session_id": "demo-session-001",
  "message": "这个岗位怎么样？",
  "jd_text": "Java后端工程师，要求掌握 Java、Spring Boot、MySQL 和 Redis。"
}
```

使用相同 `session_id` 追问时可以不传 `jd_text`：

```json
{
  "session_id": "demo-session-001",
  "message": "那和刚才那个比呢？"
}
```

`GET /users/{user_id}/agents/job/sessions/{session_id}` 可以查看当前 Session 的最近对话与岗位分析缓存。Redis 数据按职责隔离：

```text
jobpilot:session:*      # Session 归属、轮次、TTL
jobpilot:memory:*       # 最近 N 轮用户/助手消息
jobpilot:cache:*        # 最近岗位分析上下文
jobpilot:checkpoint:*   # LangGraph 执行状态
```

当前实现使用 `redis-py asyncio` 和普通 Redis 命令实现 LangGraph Checkpointer，不要求 RedisJSON 或 RediSearch。MySQL 保存业务关系，Milvus 保存简历检索块及父块内容；Redis 数据均设置 TTL。

## 多岗位对比与技能差距

阶段 8 新增 `POST /users/{user_id}/agents/job/compare`。比较前可通过
`GET /users/{user_id}/jobs` 查询历史 JD ID，也可以在比较请求中直接粘贴新 JD。
新粘贴的 JD 会复用现有解析流程并保存到历史记录。

比较流程固定为：

```text
get_candidate_profile
  → compare_jobs
      → 读取或解析 2～5 个 JD
      → 分别调用 MatchService
      → Python 按规则分数排序
      → LLM 生成技能差距与推荐理由
  → Final Answer
```

历史 JD 对比请求示例：

```json
{
  "message": "帮我比较一下字节和美团这两个 Java 实习岗位，哪个更适合我？",
  "jobs": [
    {"job_id": 1, "label": "字节"},
    {"job_id": 2, "label": "美团"}
  ]
}
```

混合历史 JD 与新粘贴 JD：

```json
{
  "message": "比较这两个岗位",
  "jobs": [
    {"job_id": 1, "label": "字节"},
    {
      "jd_text": "美团 Java 后端实习生，要求熟悉 Java、Redis、Kafka……",
      "label": "美团"
    }
  ]
}
```

`label` 用于展示公司或岗位别名，可以省略。每个元素必须且只能提供 `job_id` 或
`jd_text` 之一。LLM 不输出分数或排名，最终推荐岗位由 Python Rule Engine 的匹配
分数确定。

## 无限轮次自适应面试

阶段 10 通过 `POST /users/{user_id}/interviews` 使用历史 `job_id` 启动面试。
第一题来自当前 Profile 绑定的结构化简历：

```json
{"job_id": 1}
```

使用 `POST /users/{user_id}/interviews/{interview_id}/answers` 回答当前题目：

```json
{
  "question_id": "q1",
  "answer": "这里填写用户答案"
}
```

系统会返回具体错误、改进建议和正确答案。答案为 `incorrect` 或 `partial` 时，下一题
针对本次回答继续追问；达到 `mastered` 时，下一题转向尚未充分考察的 JD 内容。
面试不设置题数和轮次上限，每轮题目、用户答案、评价和正确答案都保存到 MySQL。
`GET /users/{user_id}/interviews/{interview_id}` 返回完整问答汇总。

## Supervisor、Resume 与 Interview Agent

统一入口为 `POST /users/{user_id}/supervisor`。Supervisor 只识别意图、选择领域
Agent、转交原始 payload 并组合结果，不调用 Repository 或具体业务 Service。
同一个前端对话应始终传递相同的 `session_id`。Supervisor 使用该标识生成稳定的
LangGraph `thread_id`，并将带 TTL 的执行快照保存到 Redis；顶层 Graph 使用
LangGraph 默认的 Checkpoint Namespace。

查看当前 Profile：

```json
{
  "session_id": "supervisor-session-001",
  "message": "查看我的候选人画像",
  "payload": {}
}
```

开始面试：

```json
{
  "session_id": "supervisor-session-001",
  "message": "根据我的简历开始模拟面试",
  "payload": {"job_id": 1}
}
```

提交面试答案：

```json
{
  "session_id": "supervisor-session-001",
  "message": "这是我对当前问题的回答，请评价并继续提问",
  "payload": {
    "interview_id": 1,
    "question_id": "q1",
    "answer": "用户回答"
  }
}
```

Resume Agent 提供 `get_resume`、`get_profile`、`update_profile` 和
`optimize_resume`；Interview Agent 提供 `create_interview_plan`、
`generate_questions`、`evaluate_answer` 和 `get_weak_points`。业务 ID 和答案由 API
payload 原样传递，Supervisor 模型不能查看或改写这些参数。

## Web 界面

FastAPI 同时托管 JobPilot 前端。启动服务后访问 `http://127.0.0.1:8000/`，系统会
自动进入 `/ui/`。界面包含聊天、Agent 切换、最近对话、简历快捷操作、无限轮面试、
上下文 ID 设置、使用统计、暗色主题和移动端布局，不需要单独启动 Node 服务。

顶部模型菜单支持按请求切换 Qwen、DeepSeek 和 GLM。浏览器通过
`X-LLM-Provider` 请求头传递选择，Supervisor 及其委派的领域 Agent 在同一次请求中共用
该模型。请在 `.env` 中分别配置 `JOBPILOT_QWEN_*`、`JOBPILOT_DEEPSEEK_*` 和
`JOBPILOT_GLM_*`；未配置 API Key 的模型会返回明确的 503 配置错误。

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
├── memory/         # Redis Session、短期 Memory、Cache 与 Checkpointer
├── parsers/        # PDF 等原始文档解析器
├── repository/     # 数据访问层
├── rules/          # 确定性的技能、学历和算分规则
├── schemas/        # Pydantic 数据模型
├── services/       # 应用服务
├── storage/        # MinIO 原始简历对象存储
├── tools/          # Agent Tool 适配层，不承载业务逻辑
└── main.py         # 应用入口
tests/              # 自动化测试
```
