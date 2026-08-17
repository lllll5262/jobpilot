# JobPilot 数据库说明

阶段 5 使用 MySQL 8、SQLAlchemy 2.x Async 和 aiomysql。数据库名为 `jobpilot`，字符集为 `utf8mb4`。原始简历 PDF 和结构化 Resume JSON 保存在 MinIO，MySQL 仅保存稳定对象地址和元数据，BGE-M3 向量保存在 Milvus，异步入库由 Celery 编排。系统不依赖 Elasticsearch。真实连接凭据只能存放在本地 `.env`。

## 表结构

### users

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT | 主键，自增 |
| email | VARCHAR(255) | 用户邮箱，唯一 |
| name | VARCHAR(100) | 用户名称，可空 |
| created_at | DATETIME | 创建时间 |

### resumes

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT | 主键，自增 |
| user_id | BIGINT | 所属用户，外键 |
| filename | VARCHAR(255) | 原 PDF 文件名 |
| doc_hash | CHAR(64) | 原 PDF SHA-256 |
| file_size_bytes | BIGINT | 文件字节数 |
| content_type | VARCHAR(100) | 文件 MIME 类型 |
| storage_bucket | VARCHAR(63) | MinIO bucket |
| storage_object_key | VARCHAR(512) | MinIO object key |
| storage_uri | VARCHAR(1024) | 稳定的 `s3://` 地址 |
| object_etag | VARCHAR(128) | MinIO ETag，可空 |
| created_at | DATETIME | 创建时间 |

原始 PDF、解析后的结构化 Resume JSON 和内容分块均不进入 MySQL。PDF 与同名
`.resume.json` 伴生对象保存在 MinIO，内容分块及向量只保存在 Milvus。下载接口根据
bucket 和 object key 动态生成短时签名 URL，数据库不保存会过期的签名地址。
`(user_id, doc_hash)` 唯一索引确保同一用户的
相同文件只生成一条 Resume；不同用户之间保持数据隔离。

同步和 Celery 异步入库最终都依赖 `(user_id, doc_hash)` 唯一索引处理并发竞争。
异步任务发布前写入的 MinIO 对象，在队列发布失败、内容校验失败、重复命中或 Milvus
索引失败时会执行补偿删除；MySQL 结构不需要额外的 Celery 任务表。

### candidate_profiles

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT | 主键，自增 |
| user_id | BIGINT | 所属用户，外键 |
| resume_id | BIGINT | 来源 Resume，外键 |
| profile_data | JSON | Candidate Profile Schema |
| is_current | BOOLEAN | 是否为当前画像 |
| created_at | DATETIME | 创建时间 |

### jobs

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT | 主键，自增 |
| user_id | BIGINT | 所属用户，外键 |
| raw_text | LONGTEXT | 原始 JD |
| parsed_data | JSON | JD Schema |
| created_at | DATETIME | 创建时间 |

### job_analyses

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT | 主键，自增 |
| user_id | BIGINT | 所属用户，外键 |
| resume_id | BIGINT | 分析使用的 Resume |
| profile_id | BIGINT | 分析使用的 Profile |
| job_id | BIGINT | 分析岗位 |
| match_score | SMALLINT | 0～100 规则分数 |
| recommendation | VARCHAR(32) | 推荐结论 |
| result_data | JSON | 完整 MatchResult |
| created_at | DATETIME | 创建时间 |

## 初始化

使用独立 SQL 文件初始化数据库和业务表：

```powershell
Get-Content "database/jobpilot_schema.sql" -Raw | mysql -h <mysql-host> -P <mysql-port> -u <mysql-user> -p
```

初始化完成后，FastAPI 应用通过 SQLAlchemy 和 aiomysql 对上述 5 张业务表执行日常增删改查。新环境使用 [jobpilot_schema.sql](database/jobpilot_schema.sql)，已有环境按下方专项脚本升级。

## 已有数据库升级

已有 `resumes` 表执行以下脚本增加 MinIO 元数据列：

```powershell
Get-Content "database/migrate_resume_minio_metadata.sql" -Raw | mysql -h <mysql-host> -P <mysql-port> -u <mysql-user> -p
```

迁移脚本不删除旧数据，新增列允许旧记录保持 `NULL`。旧记录需要重新上传原始 PDF 后，
才能使用 MinIO 下载接口。当对象元数据已补齐后，依次执行：

```powershell
# 1. 只校验，不写 MinIO
.\.venv\Scripts\python.exe "database/migrate_resume_content_to_minio.py"

# 2. 将 resumes.parsed_data 写成 MinIO 伴生 .resume.json
.\.venv\Scripts\python.exe "database/migrate_resume_content_to_minio.py" --apply

# 3. 备份并确认前两步无 skipped 后，删除 MySQL 正文列
Get-Content "database/drop_resume_parsed_data.sql" -Raw | mysql -h <mysql-host> -P <mysql-port> -u <mysql-user> -p
```

部署顺序不能颠倒：旧库的 `parsed_data` 列是 `NOT NULL` 时，新版应用只能在第 3 步完成后启动。

当前 `resume_id=6` 的原始 PDF 已上传到 MinIO，可在结构迁移完成后执行
`database/backfill_resume_6_minio.sql` 写入对应对象元数据：

```powershell
Get-Content "database/backfill_resume_6_minio.sql" -Raw | mysql -h <mysql-host> -P <mysql-port> -u <mysql-user> -p
```
