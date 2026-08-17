-- 只能在 migrate_resume_content_to_minio.py --apply 成功完成后执行。
-- 该操作会删除旧的结构化简历列，执行前请备份数据库。
USE `jobpilot`;

ALTER TABLE `resumes`
  DROP COLUMN `parsed_data`;
