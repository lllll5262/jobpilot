-- 在 migrate_resume_minio_metadata.sql 成功执行后运行。
-- 将已上传到 MinIO 的原始 PDF 元数据绑定到 user_id=1 / resume_id=6。

USE `jobpilot`;

START TRANSACTION;

UPDATE `resumes`
SET
  `doc_hash` = 'f9ab63e78249d46a6498e9c197ca753bbf071773cda98d8e6189e98c472ab63e',
  `file_size_bytes` = 207275,
  `content_type` = 'application/pdf',
  `storage_bucket` = 'jobpilot-resumes',
  `storage_object_key` = 'users/1/resumes/0ec0ef827a834928ad7fddaa08b4bc9b.pdf',
  `storage_uri` = 's3://jobpilot-resumes/users/1/resumes/0ec0ef827a834928ad7fddaa08b4bc9b.pdf',
  `object_etag` = '767b28a33d05c75a6c6947ae96a7805f'
WHERE `id` = 6
  AND `user_id` = 1
  AND `storage_uri` IS NULL;

SELECT ROW_COUNT() AS `updated_resume_rows`;

COMMIT;
