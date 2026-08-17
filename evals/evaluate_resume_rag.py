"""调用简历 RAG 接口，并用 RAGAS 评估回答质量。"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

import httpx
from openai import AsyncOpenAI
from ragas.embeddings.base import embedding_factory
from ragas.llms import llm_factory
from ragas.metrics.collections import AnswerCorrectness, AnswerRelevancy, Faithfulness


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
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def required_env(name: str) -> str:
    """读取非空评估配置，避免静默使用错误的评审模型。"""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def load_cases(path: Path) -> list[dict[str, Any]]:
    """加载并校验最小评估数据格式。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("evaluation dataset must be a non-empty JSON array")
    for index, case in enumerate(raw):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        for field in ("resume_id", "question", "reference"):
            if not case.get(field):
                raise ValueError(f"case {index} is missing {field}")
    return raw


async def request_answer(
    *,
    client: httpx.AsyncClient,
    user_id: int,
    provider: str,
    case: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    """请求真实生成链路，保留实际注入模型的父块上下文。"""
    response = await client.post(
        f"/users/{user_id}/resumes/answer",
        headers={"X-LLM-Provider": provider},
        json={
            "query": case["question"],
            "resume_id": case["resume_id"],
            "limit": limit,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        raise RuntimeError(f"RAG endpoint failed: {payload.get('message', 'unknown error')}")
    return payload["data"]


async def run() -> None:
    """逐条生成回答并计算三个 RAGAS 指标。"""
    args = parse_args()
    cases = load_cases(args.dataset)

    evaluator_client = AsyncOpenAI(
        api_key=required_env("JOBPILOT_RAGAS_API_KEY"),
        base_url=required_env("JOBPILOT_RAGAS_BASE_URL"),
    )
    evaluator_llm = llm_factory(
        required_env("JOBPILOT_RAGAS_JUDGE_MODEL"),
        provider="openai",
        client=evaluator_client,
    )
    evaluator_embeddings = embedding_factory(
        "openai",
        model=required_env("JOBPILOT_RAGAS_EMBEDDING_MODEL"),
        client=evaluator_client,
        interface="modern",
    )

    faithfulness = Faithfulness(llm=evaluator_llm)
    answer_relevancy = AnswerRelevancy(
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
    )
    answer_correctness = AnswerCorrectness(
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
    )

    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=args.base_url, timeout=120.0) as rag_client:
        for case in cases:
            generated = await request_answer(
                client=rag_client,
                user_id=args.user_id,
                provider=args.provider,
                case=case,
                limit=args.limit,
            )
            contexts = [item["parent_content"] for item in generated["contexts"]]
            response = generated["answer"]

            faithfulness_result = await faithfulness.ascore(
                user_input=case["question"],
                response=response,
                retrieved_contexts=contexts,
            )
            relevancy_result = await answer_relevancy.ascore(
                user_input=case["question"],
                response=response,
            )
            correctness_result = await answer_correctness.ascore(
                user_input=case["question"],
                response=response,
                reference=case["reference"],
            )
            rows.append(
                {
                    "resume_id": case["resume_id"],
                    "question": case["question"],
                    "reference": case["reference"],
                    "answer": response,
                    "cited_parent_ids": generated["cited_parent_ids"],
                    "faithfulness": faithfulness_result.value,
                    "answer_relevancy": relevancy_result.value,
                    "answer_correctness": correctness_result.value,
                }
            )

    metric_names = ("faithfulness", "answer_relevancy", "answer_correctness")
    summary = {name: fmean(row[name] for row in rows) for name in metric_names}
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(rows),
        "summary": summary,
        "cases": rows,
    }
    output = args.output or Path(
        f"evals/results/resume_rag_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report: {output}")


if __name__ == "__main__":
    asyncio.run(run())

