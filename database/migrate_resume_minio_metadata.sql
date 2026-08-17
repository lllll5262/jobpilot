-- 已有 JobPilot 数据库迁移：为 resumes 增加 MinIO 对象元数据。
-- 该脚本不删除数据；执行前请先备份数据库，并且只执行一次。

USE `jobpilot`;

ALTER TABLE `resumes`
  ADD COLUMN `doc_hash` CHAR(64) NULL AFTER `filename`,
  ADD COLUMN `file_size_bytes` BIGINT NULL AFTER `doc_hash`,
  ADD COLUMN `content_type` VARCHAR(100) NULL AFTER `file_size_bytes`,
  ADD COLUMN `storage_bucket` VARCHAR(63) NULL AFTER `content_type`,
  ADD COLUMN `storage_object_key` VARCHAR(512) NULL AFTER `storage_bucket`,
  ADD COLUMN `storage_uri` VARCHAR(1024) NULL AFTER `storage_object_key`,
  ADD COLUMN `object_etag` VARCHAR(128) NULL AFTER `storage_uri`,
  ADD UNIQUE INDEX `uq_resumes_storage_object` (`storage_bucket`, `storage_object_key`);

-- 旧记录没有原始 PDF 对象，以上字段保留 NULL；重新上传后新记录会完整写入元数据。
