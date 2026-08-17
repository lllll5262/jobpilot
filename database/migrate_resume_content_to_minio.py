"""把旧 resumes.parsed_data 回填为 MinIO 结构化简历对象。

默认只检查；传入 --apply 才会写入 MinIO。必须在删除 parsed_data 列之前执行。
"""

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import text

from app.db.database import async_session_factory, dispose_database
from app.schemas.resume import ResumeParseResult
from app.storage.dependencies import dispose_resume_object_store, get_resume_object_store


def _normalize_parsed_data(value: Any) -> ResumeParseResult:
    if isinstance(value, str):
        value = json.loads(value)
    return ResumeParseResult.model_validate(value)


async def migrate(*, apply: bool) -> None:
    statement = text(
        """
        SELECT id, storage_bucket, storage_object_key, parsed_data
        FROM resumes
        WHERE parsed_data IS NOT NULL
        ORDER BY id
        """
    )
    migrated = 0
    skipped = 0
    object_store = get_resume_object_store()
    try:
        async with async_session_factory() as session:
            rows = (await session.execute(statement)).mappings().all()

        for row in rows:
            bucket = row["storage_bucket"]
            object_key = row["storage_object_key"]
            if not bucket or not object_key:
                skipped += 1
                print(f"SKIP resume_id={row['id']}: missing MinIO object metadata")
                continue

            resume = _normalize_parsed_data(row["parsed_data"])
            payload = json.dumps(
                resume.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if apply:
                await object_store.save_parsed_resume(
                    bucket=bucket,
                    pdf_object_key=object_key,
                    content=payload,
                )
                stored_payload = await object_store.read_parsed_resume(
                    bucket=bucket,
                    pdf_object_key=object_key,
                )
                if ResumeParseResult.model_validate_json(stored_payload) != resume:
                    raise RuntimeError(f"MinIO verification failed for resume_id={row['id']}")
                print(f"WRITE resume_id={row['id']}: {object_key[:-4]}.resume.json")
            else:
                print(f"CHECK resume_id={row['id']}: ready")
            migrated += 1
    finally:
        await dispose_resume_object_store()
        await dispose_database()

    mode = "written" if apply else "validated"
    print(f"Done: {migrated} {mode}, {skipped} skipped")
    if skipped:
        raise SystemExit("Migration incomplete: fix skipped rows before dropping parsed_data")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write validated structured resume JSON objects to MinIO",
    )
    args = parser.parse_args()
    asyncio.run(migrate(apply=args.apply))


if __name__ == "__main__":
    main()
