"""调用简历 RAG 接口，并用 RAGAS 评估回答质量。"""

import argparse
import asyncio
import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

import httpx
from dotenv import dotenv_values
from openai import AsyncOpenAI
from ragas.cache import DiskCacheBackend
from ragas.embeddings.base import embedding_factory
from ragas.llms import llm_factory
from ragas.metrics.collections import (
    AnswerCorrectness,
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)


def parse_args() -> argparse.Namespace:
    """解析目标服务、数据集和输出位置。"""
    parser = argparse.ArgumentParser(description="评估 JobPilot 简历 RAG 生成链路")
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/resume_rag.json"),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--provider", choices=["qwen", "deepseek", "glm"], default="qwen")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--generation-retries", type=int, default=2)
    parser.add_argument("--cache-dir", type=Path, default=Path("evals/.ragas_cache"))
    parser.add_argument("--include-answer-correctness", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    return parser.parse_args()


def resolve_evaluator_config() -> dict[str, str]:
    """优先使用独立评测配置，否则复用项目现有通义千问配置。"""
    project_env = {
        key: value or ""
        for key, value in dotenv_values(Path(__file__).resolve().parents[1] / ".env").items()
    }
    config = {**project_env, **os.environ}
    api_key = (
        config.get("JOBPILOT_RAGAS_API_KEY", "").strip()
        or config.get("JOBPILOT_QWEN_API_KEY", "").strip()
        or config.get("JOBPILOT_LLM_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError("JOBPILOT_RAGAS_API_KEY or JOBPILOT_LLM_API_KEY is required")
    return {
        "api_key": api_key,
        "base_url": config.get("JOBPILOT_RAGAS_BASE_URL", "").strip()
        or config.get("JOBPILOT_LLM_BASE_URL", "").strip()
        or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "judge_model": config.get("JOBPILOT_RAGAS_JUDGE_MODEL", "").strip()
        or config.get("JOBPILOT_LLM_MODEL", "").strip()
        or "qwen-plus",
        "embedding_model": config.get(
            "JOBPILOT_RAGAS_EMBEDDING_MODEL", ""
        ).strip()
        or "text-embedding-v4",
    }


def load_cases(path: Path) -> list[dict[str, Any]]:
    """加载 CSV 或 JSON，并校验最小评估数据格式。"""
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw: Any = list(csv.DictReader(handle))
    else:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("evaluation dataset must be a non-empty CSV or JSON array")
    for index, case in enumerate(raw):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        for field in ("resume_id", "question", "reference"):
            if not case.get(field):
                raise ValueError(f"case {index} is missing {field}")
        try:
            case["resume_id"] = int(case["resume_id"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"case {index} has invalid resume_id") from exc
    return raw


def write_csv_report(path: Path, rows: list[dict[str, Any]]) -> None:
    """输出便于人工筛选的 UTF-8 BOM 逐题结果。"""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    metric_fields = [
        name
        for name in (
            "context_precision",
            "context_recall",
            "faithfulness",
            "answer_relevancy",
            "answer_correctness",
        )
        if name in rows[0]
    ]
    fieldnames = [
        "resume_id",
        "question",
        "reference",
        "answer",
        "generation_attempts",
        "context_count",
        "cited_parent_ids",
        *metric_fields,
        "retrieved_contexts",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{field: row.get(field) for field in fieldnames},
                    "cited_parent_ids": " | ".join(row["cited_parent_ids"]),
                    "retrieved_contexts": json.dumps(
                        row["retrieved_contexts"], ensure_ascii=False
                    ),
                }
            )


async def request_answer(
    *,
    client: httpx.AsyncClient,
    user_id: int,
    provider: str,
    case: dict[str, Any],
    limit: int,
    retries: int,
) -> dict[str, Any]:
    """请求真实生成链路，保留实际注入模型的父块上下文。"""
    for attempt in range(1, retries + 2):
        response = await client.post(
            f"/users/{user_id}/resumes/answer",
            headers={"X-LLM-Provider": provider},
            json={
                "query": case["question"],
                "resume_id": case["resume_id"],
                "limit": limit,
            },
        )
        payload = response.json()
        if payload.get("code") == 50240 and attempt <= retries:
            continue
        response.raise_for_status()
        if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
            raise RuntimeError(
                f"RAG endpoint failed: {payload.get('message', 'unknown error')}"
            )
        result = payload["data"]
        result["_generation_attempts"] = attempt
        return result
    raise RuntimeError("RAG endpoint exhausted generation retries")


async def run() -> None:
    """逐条生成回答并计算四个核心 RAGAS 指标。"""
    args = parse_args()
    cases = load_cases(args.dataset)
    if args.max_cases is not None:
        if args.max_cases < 1:
            raise ValueError("max-cases must be at least 1")
        cases = cases[: args.max_cases]
    if args.concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if args.generation_retries < 0:
        raise ValueError("generation-retries cannot be negative")

    evaluator_config = resolve_evaluator_config()
    evaluator_client = AsyncOpenAI(
        api_key=evaluator_config["api_key"],
        base_url=evaluator_config["base_url"],
    )
    cache = DiskCacheBackend(str(args.cache_dir))
    evaluator_llm = llm_factory(
        evaluator_config["judge_model"],
        provider="openai",
        client=evaluator_client,
        cache=cache,
        max_tokens=8192,
    )
    evaluator_embeddings = embedding_factory(
        "openai",
        model=evaluator_config["embedding_model"],
        client=evaluator_client,
        interface="modern",
        cache=cache,
    )

    context_precision = ContextPrecision(llm=evaluator_llm)
    context_recall = ContextRecall(llm=evaluator_llm)
    faithfulness = Faithfulness(llm=evaluator_llm)
    answer_relevancy = AnswerRelevancy(
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
    )
    answer_correctness = (
        AnswerCorrectness(llm=evaluator_llm, embeddings=evaluator_embeddings)
        if args.include_answer_correctness
        else None
    )

    semaphore = asyncio.Semaphore(args.concurrency)
    completed = 0
    progress_lock = asyncio.Lock()

    async with httpx.AsyncClient(base_url=args.base_url, timeout=120.0) as rag_client:
        async def evaluate_case(index: int, case: dict[str, Any]) -> dict[str, Any]:
            nonlocal completed
            async with semaphore:
                generated = await request_answer(
                    client=rag_client,
                    user_id=args.user_id,
                    provider=args.provider,
                    case=case,
                    limit=args.limit,
                    retries=args.generation_retries,
                )
                contexts = [item["parent_content"] for item in generated["contexts"]]
                response = generated["answer"]
                score_tasks = [
                    context_precision.ascore(
                        user_input=case["question"],
                        reference=case["reference"],
                        retrieved_contexts=contexts,
                    ),
                    context_recall.ascore(
                        user_input=case["question"],
                        reference=case["reference"],
                        retrieved_contexts=contexts,
                    ),
                    faithfulness.ascore(
                        user_input=case["question"],
                        response=response,
                        retrieved_contexts=contexts,
                    ),
                    answer_relevancy.ascore(
                        user_input=case["question"],
                        response=response,
                    ),
                ]
                if answer_correctness is not None:
                    score_tasks.append(
                        answer_correctness.ascore(
                            user_input=case["question"],
                            response=response,
                            reference=case["reference"],
                        )
                    )
                scores = await asyncio.gather(*score_tasks)
                row = {
                    "_index": index,
                    "resume_id": case["resume_id"],
                    "question": case["question"],
                    "reference": case["reference"],
                    "answer": response,
                    "generation_attempts": generated["_generation_attempts"],
                    "context_count": len(contexts),
                    "cited_parent_ids": generated["cited_parent_ids"],
                    "retrieved_contexts": contexts,
                    "context_precision": scores[0].value,
                    "context_recall": scores[1].value,
                    "faithfulness": scores[2].value,
                    "answer_relevancy": scores[3].value,
                }
                if answer_correctness is not None:
                    row["answer_correctness"] = scores[4].value
                async with progress_lock:
                    completed += 1
                    print(f"progress: {completed}/{len(cases)}", flush=True)
                return row

        rows = await asyncio.gather(
            *(evaluate_case(index, case) for index, case in enumerate(cases))
        )

    rows.sort(key=lambda row: row["_index"])
    for row in rows:
        row.pop("_index")
    metric_names = [
        "context_precision",
        "context_recall",
        "faithfulness",
        "answer_relevancy",
    ]
    if args.include_answer_correctness:
        metric_names.append("answer_correctness")
    summary = {name: fmean(row[name] for row in rows) for name in metric_names}
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(rows),
        "evaluator": {
            "base_url": evaluator_config["base_url"],
            "judge_model": evaluator_config["judge_model"],
            "embedding_model": evaluator_config["embedding_model"],
        },
        "summary": summary,
        "cases": rows,
    }
    output = args.output or Path(
        f"evals/results/resume_rag_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_output = args.csv_output or output.with_suffix(".csv")
    write_csv_report(csv_output, rows)
    await evaluator_client.close()
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report: {output}")
    print(f"csv: {csv_output}")


if __name__ == "__main__":
    asyncio.run(run())
