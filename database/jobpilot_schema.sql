-- JobPilot 阶段 5：MySQL 8 初始化脚本
-- 说明：脚本不包含 DROP 操作，不会删除现有数据库或表。

CREATE DATABASE IF NOT EXISTS `jobpilot`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `jobpilot`;

-- 用户：保存系统中的候选人账号。
CREATE TABLE `users` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(255) NOT NULL,
  `name` VARCHAR(100) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `pk_users` PRIMARY KEY (`id`),
  CONSTRAINT `uq_users_email` UNIQUE (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 简历：只保存 MinIO 对象元数据；PDF 和结构化 Resume JSON 均保存在 MinIO。
CREATE TABLE `resumes` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL,
  `filename` VARCHAR(255) NOT NULL,
  `doc_hash` CHAR(64) NOT NULL,
  `file_size_bytes` BIGINT NOT NULL,
  `content_type` VARCHAR(100) NOT NULL DEFAULT 'application/pdf',
  `storage_bucket` VARCHAR(63) NOT NULL,
  `storage_object_key` VARCHAR(512) NOT NULL,
  `storage_uri` VARCHAR(1024) NOT NULL,
  `object_etag` VARCHAR(128) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `pk_resumes` PRIMARY KEY (`id`),
  CONSTRAINT `fk_resumes_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  INDEX `ix_resumes_user_created` (`user_id`, `created_at`),
  UNIQUE INDEX `uq_resumes_user_doc_hash` (`user_id`, `doc_hash`),
  UNIQUE INDEX `uq_resumes_storage_object` (`storage_bucket`, `storage_object_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 候选人画像：与原始简历分开保存，is_current 标识用户当前画像。
CREATE TABLE `candidate_profiles` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL,
  `resume_id` BIGINT NOT NULL,
  `profile_data` JSON NOT NULL,
  `is_current` BOOLEAN NOT NULL DEFAULT TRUE,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `pk_candidate_profiles` PRIMARY KEY (`id`),
  CONSTRAINT `fk_candidate_profiles_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_candidate_profiles_resume_id_resumes`
    FOREIGN KEY (`resume_id`) REFERENCES `resumes` (`id`) ON DELETE CASCADE,
  INDEX `ix_candidate_profiles_user_current` (`user_id`, `is_current`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 岗位：同时保存原始 JD 和解析后的结构化 JSON。
CREATE TABLE `jobs` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL,
  `raw_text` LONGTEXT NOT NULL,
  `parsed_data` JSON NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `pk_jobs` PRIMARY KEY (`id`),
  CONSTRAINT `fk_jobs_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  INDEX `ix_jobs_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 岗位分析：保存一次 Resume/Profile/JD 的完整匹配结果。
CREATE TABLE `job_analyses` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL,
  `resume_id` BIGINT NOT NULL,
  `profile_id` BIGINT NOT NULL,
  `job_id` BIGINT NOT NULL,
  `match_score` SMALLINT NOT NULL,
  `recommendation` VARCHAR(32) NOT NULL,
  `result_data` JSON NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `pk_job_analyses` PRIMARY KEY (`id`),
  CONSTRAINT `ck_job_analyses_match_score_range`
    CHECK (`match_score` BETWEEN 0 AND 100),
  CONSTRAINT `fk_job_analyses_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_job_analyses_resume_id_resumes`
    FOREIGN KEY (`resume_id`) REFERENCES `resumes` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_job_analyses_profile_id_candidate_profiles`
    FOREIGN KEY (`profile_id`) REFERENCES `candidate_profiles` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_job_analyses_job_id_jobs`
    FOREIGN KEY (`job_id`) REFERENCES `jobs` (`id`) ON DELETE CASCADE,
  INDEX `ix_job_analyses_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
