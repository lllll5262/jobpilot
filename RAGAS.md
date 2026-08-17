# 简历 RAG 生成与 RAGAS 评估

## 生成接口

`POST /users/{user_id}/resumes/answer` 执行完整生成链路：

```text
问题 → BGE-M3 查询向量 → Milvus 混合检索 → 父块去重
     → 将父块注入 LLM → 校验引用 parent_id → 返回回答与上下文
```

请求示例：

```json
{
  "query": "候选人是否有 Redis 高并发项目经验？",
  "resume_id": 1,
  "limit": 8
}
```

可通过 `X-LLM-Provider: qwen|deepseek|glm` 选择生成模型。回答中的
`cited_parent_ids` 必须属于本次返回的 `contexts`，否则接口拒绝该模型输出。

## 准备评估数据

评估数据支持 JSON，也支持带 UTF-8 BOM 的 CSV。CSV 必须包含三列：

```csv
resume_id,question,reference
6,硕士阶段的专业是什么？,硕士阶段的专业是电子信息。
```

也可以复制 JSON 示例文件并填写真实简历 ID、问题和人工核验的标准答案：

```powershell
Copy-Item "evals/datasets/resume_rag.example.json" "evals/datasets/resume_rag.json"
```

标准答案必须来自对应简历，不能由被测生成模型自动编造。

## 安装评估依赖

```powershell
python -m pip install -r requirements-eval.txt
```

## 配置评审模型

RAGAS 评审模型与业务生成模型独立配置。下面以支持 OpenAI-compatible Chat 和
Embeddings API 的服务为例：

评估会把问题、生成答案、标准答案和检索到的简历父块发送给评审服务。真实简历
属于敏感数据，运行前必须确认所选服务和数据处理策略符合你的合规要求。

```powershell
$env:JOBPILOT_RAGAS_API_KEY="your-key"
$env:JOBPILOT_RAGAS_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:JOBPILOT_RAGAS_JUDGE_MODEL="qwen-plus"
$env:JOBPILOT_RAGAS_EMBEDDING_MODEL="text-embedding-v4"
```

## 运行

先启动 JobPilot 及 MySQL、Milvus，再执行：

```powershell
python "evals/evaluate_resume_rag.py" `
  --user-id 1 `
  --provider qwen `
  --dataset "E:/resume/李英杰_简历_RAGAS_40问答_无候选人.csv"
```

脚本调用真实生成接口，并计算：

- `context_precision`：排名靠前的检索上下文是否真正支持标准答案。
- `context_recall`：检索上下文是否覆盖标准答案中的事实。
- `faithfulness`：回答中的陈述能否由实际检索上下文支持。
- `answer_relevancy`：回答是否直接回应问题。

如需额外计算回答与人工标准答案的一致性，可传入
`--include-answer-correctness` 启用 `answer_correctness`。

JSON 审计报告和 UTF-8 CSV 逐题结果保存在 `evals/results/`。脚本默认启用本地
RAGAS 缓存，并对引用格式失败的生成请求最多重试两次。应使用同一评估集比较检索参数、Prompt
或模型变更，不应把单次绝对分数直接当作通用质量标准。
