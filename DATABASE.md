# JobPilot 数据库说明

阶段 5 使用 MySQL 8、SQLAlchemy 2.x Async 和 aiomysql。数据库名为 `jobpilot`，字符集为 `utf8mb4`。真实连接凭据只能存放在本地 `.env`。

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
| parsed_data | JSON | Resume Schema |
| created_at | DATETIME | 创建时间 |

原始 PDF 二进制不入库，仅保存文件名与结构化结果。

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

初始化完成后，FastAPI 应用通过 SQLAlchemy 和 aiomysql 对上述 5 张业务表执行增删改查。当前阶段不包含数据库结构迁移逻辑；如需调整表结构，应同步修改 ORM Model 与 [jobpilot_schema.sql](database/jobpilot_schema.sql)。
