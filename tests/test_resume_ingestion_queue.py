"""Celery 简历入库消息与状态适配测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.storage.resume_object_store import ResumeObjectMetadata
from app.tasks.resume_ingestion_queue import CeleryResumeIngestionQueue


def test_queue_message_contains_only_minio_metadata(monkeypatch: object) -> None:
    """Celery 消息不得包含 PDF bytes，只传稳定对象地址和校验信息。"""
    sent: dict[str, object] = {}

    def fake_send_task(name: str, **values: object) -> None:
        sent["name"] = name
        sent.update(values)

    from app.tasks import resume_ingestion_queue as queue_module

    monkeypatch.setattr(queue_module.celery_app, "send_task", fake_send_task)  # type: ignore[attr-defined]
    queue = CeleryResumeIngestionQueue()
    task_id = queue.enqueue(
        user_id=7,
        filename="resume.pdf",
        doc_hash="a" * 64,
        stored_object=ResumeObjectMetadata(
            bucket="jobpilot-resumes",
            object_key="users/7/resumes/staged.pdf",
            storage_uri="s3://jobpilot-resumes/users/7/resumes/staged.pdf",
            etag="etag",
            size_bytes=1024,
            content_type="application/pdf",
        ),
    )

    assert task_id.startswith("resume-7-")
    assert sent["name"] == "jobpilot.resume.ingest"
    assert "pdf_content" not in str(sent)
    assert sent["task_id"] == task_id


def test_queue_success_status_restores_resume_record(monkeypatch: object) -> None:
    """成功任务结果应恢复为类型安全的 ResumeRecord。"""
    from app.tasks import resume_ingestion_queue as queue_module

    result = SimpleNamespace(
        state="SUCCESS",
        result={
            "user_id": 7,
            "resume": {
                "id": 10,
                "user_id": 7,
                "filename": "resume.pdf",
                "resume": {
                    "personal_info": {
                        "name": "测试用户",
                        "email": None,
                        "phone": None,
                        "location": None,
                    },
                    "education": [],
                    "skills": ["Java"],
                    "projects": [],
                    "internships": [],
                    "certificates": [],
                },
                "created_at": datetime(2026, 8, 17, tzinfo=UTC).isoformat(),
            },
        },
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        queue_module.celery_app,
        "AsyncResult",
        lambda _: result,
    )

    status = CeleryResumeIngestionQueue().get_status(
        user_id=7,
        task_id="resume-7-12345678901234567890123456789012",
    )

    assert status.status == "succeeded"
    assert status.resume is not None
    assert status.resume.id == 10
