-- JobPilot 阶段 10：自适应面试会话表
-- 仅新增表，不修改或删除阶段 8 的现有表和数据。

USE `jobpilot`;

CREATE TABLE IF NOT EXISTS `interview_sessions` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL,
  `resume_id` BIGINT NOT NULL,
  `profile_id` BIGINT NOT NULL,
  `job_id` BIGINT NOT NULL,
  `rounds_data` JSON NOT NULL,
  `weak_points` JSON NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT `pk_interview_sessions` PRIMARY KEY (`id`),
  CONSTRAINT `fk_interview_sessions_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_interview_sessions_resume_id_resumes`
    FOREIGN KEY (`resume_id`) REFERENCES `resumes` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_interview_sessions_profile_id_candidate_profiles`
    FOREIGN KEY (`profile_id`) REFERENCES `candidate_profiles` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_interview_sessions_job_id_jobs`
    FOREIGN KEY (`job_id`) REFERENCES `jobs` (`id`) ON DELETE CASCADE,
  INDEX `ix_interview_sessions_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
