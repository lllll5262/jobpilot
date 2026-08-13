"""自适应面试 Agent 对外门面。"""

from app.agents.interview_agent.graph import InterviewAgentGraph
from app.core.exceptions import AppException
from app.schemas.interview import (
    InterviewAgentAction,
    InterviewAgentPayload,
    InterviewAgentResult,
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewSessionRecord,
    InterviewStartRequest,
)
from app.services.interview_service import InterviewService
from app.tools.interview_tools import (
    AnswerInterviewTool,
    GetCurrentQuestionTool,
    GetWeakPointsTool,
    StartInterviewTool,
)


class InterviewAgent:
    """使用 LangGraph 执行启动面试和提交答案流程。"""

    def __init__(self, *, user_id: int, service: InterviewService) -> None:
        self._user_id = user_id
        self._service = service
        self._graph = InterviewAgentGraph(
            start_tool=StartInterviewTool(user_id=user_id, service=service),
            answer_tool=AnswerInterviewTool(user_id=user_id, service=service),
        )
        self._get_question_tool = GetCurrentQuestionTool(user_id=user_id, service=service)
        self._get_weak_points_tool = GetWeakPointsTool(user_id=user_id, service=service)

    async def start(self, request: InterviewStartRequest) -> InterviewSessionRecord:
        """启动面试并返回第一题。"""
        state = await self._graph.run(
            {
                "action": "start",
                "payload": request.model_dump(mode="json"),
                "tool_trace": [],
            }
        )
        return InterviewSessionRecord.model_validate(state["result"])

    async def answer(
        self,
        *,
        session_id: int,
        request: InterviewAnswerRequest,
    ) -> InterviewAnswerResponse:
        """评价答案并返回追问或下一道 JD 题。"""
        state = await self._graph.run(
            {
                "action": "answer",
                "payload": {
                    "session_id": session_id,
                    "request": request.model_dump(mode="json"),
                },
                "tool_trace": [],
            }
        )
        return InterviewAnswerResponse.model_validate(state["result"])

    async def execute(
        self,
        *,
        action: InterviewAgentAction,
        payload: dict[str, object],
    ) -> InterviewAgentResult:
        """执行 Supervisor 委派的 Interview 动作。"""
        params = InterviewAgentPayload.model_validate(payload)
        if action == InterviewAgentAction.CREATE_INTERVIEW_PLAN:
            if params.job_id is None:
                raise AppException("job_id is required", code=42230, status_code=422)
            result = await self.start(InterviewStartRequest(job_id=params.job_id))
            tool_name = "create_interview_plan"
            data = result.model_dump(mode="json")
        elif action == InterviewAgentAction.EVALUATE_ANSWER:
            if (
                params.interview_id is None
                or params.question_id is None
                or params.answer is None
            ):
                raise AppException(
                    "interview_id, question_id and answer are required",
                    code=42231,
                    status_code=422,
                )
            result = await self.answer(
                session_id=params.interview_id,
                request=InterviewAnswerRequest(
                    question_id=params.question_id,
                    answer=params.answer,
                ),
            )
            tool_name = "evaluate_answer"
            data = result.model_dump(mode="json")
        elif action == InterviewAgentAction.GET_WEAK_POINTS:
            if params.interview_id is None:
                raise AppException("interview_id is required", code=42232, status_code=422)
            tool_name = self._get_weak_points_tool.name
            data = await self._get_weak_points_tool.invoke(
                {"interview_id": params.interview_id}
            )
        else:
            if params.interview_id is None:
                raise AppException("interview_id is required", code=42232, status_code=422)
            tool_name = self._get_question_tool.name
            data = await self._get_question_tool.invoke(
                {"interview_id": params.interview_id}
            )
        return InterviewAgentResult(
            action=action.value,
            result=data,
            tool_trace=[tool_name],
        )
