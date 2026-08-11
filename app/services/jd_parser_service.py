"""JD 解析应用服务。"""

from app.llm.client import JSONGenerator
from app.llm.prompts.jd_parser import (
    build_jd_parser_system_prompt,
    build_jd_parser_user_prompt,
)
from app.schemas.job import JDParseResult
from app.services.structured_output import generate_structured_output


class JDParserService:
    """编排 Prompt、LLM 调用和 Pydantic 结构化校验。"""

    def __init__(self, llm_client: JSONGenerator) -> None:
        self._llm_client = llm_client

    async def parse(self, jd_text: str) -> JDParseResult:
        """解析 JD；模型输出只有通过 Schema 校验后才能返回。"""
        return await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_jd_parser_system_prompt(),
            user_prompt=build_jd_parser_user_prompt(jd_text),
            schema=JDParseResult,
            log_context="jd_parser",
        )
