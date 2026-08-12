"""面试 Agent Tool 适配层。"""

from typing import Any

from app.schemas.interview import InterviewAnswerRequest, InterviewStartRequest
from app.services.interview_service import InterviewService


class StartInterviewTool:
    """将可信 Graph 输入适配到启动面试 Service。"""

    name = "create_interview_plan"

    def __init__(self, *, user_id: int, service: InterviewService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """生成第一道简历问题并保存会话。"""
        request = InterviewStartRequest.model_validate(payload)
        result = await self._service.start(user_id=self._user_id, request=request)
        return result.model_dump(mode="json")


class AnswerInterviewTool:
    """将可信 Graph 输入适配到答案评价 Service。"""

    name = "evaluate_answer"

    def __init__(self, *, user_id: int, service: InterviewService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """评价本轮答案并决定下一题。"""
        request = InterviewAnswerRequest.model_validate(payload["request"])
        result = await self._service.answer(
            user_id=self._user_id,
            session_id=int(payload["session_id"]),
            request=request,
        )
        return result.model_dump(mode="json")


class GetWeakPointsTool:
    """读取并确定性汇总当前面试的薄弱点。"""

    name = "get_weak_points"

    def __init__(self, *, user_id: int, service: InterviewService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """返回薄弱点出现次数和最近分数。"""
        session_id = int(payload["interview_id"])
        result = await self._service.get_weak_points(
            user_id=self._user_id,
            session_id=session_id,
        )
        return {"weak_points": [item.model_dump(mode="json") for item in result]}


class GetCurrentQuestionTool:
    """读取当前等待作答的问题。"""

    name = "generate_questions"

    def __init__(self, *, user_id: int, service: InterviewService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """无限面试每轮只生成一题；已有待答题时直接返回，避免跳题。"""
        session_id = int(payload["interview_id"])
        session = await self._service.get_session(
            user_id=self._user_id,
            session_id=session_id,
        )
        return {
            "interview_id": session.id,
            "current_question": (
                session.current_question.model_dump(mode="json")
                if session.current_question is not None
                else None
            ),
        }
