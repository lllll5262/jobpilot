"""多轮 Job Agent 会话编排服务。"""

from app.agents.job_agent import JobAgent
from app.core.exceptions import AppException
from app.memory.conversation_memory import ConversationMemory
from app.memory.session_store import AnalysisContextCache, SessionStore
from app.schemas.agent import (
    JobAgentSessionRequest,
    JobAgentSessionResponse,
    JobAgentSessionState,
)


class SessionService:
    """协调 Session、短期 Memory、Cache 与单 Job Agent。"""

    def __init__(
        self,
        *,
        session_store: SessionStore,
        conversation_memory: ConversationMemory,
        analysis_cache: AnalysisContextCache,
    ) -> None:
        self._session_store = session_store
        self._conversation_memory = conversation_memory
        self._analysis_cache = analysis_cache

    async def chat(
        self,
        *,
        user_id: int,
        request: JobAgentSessionRequest,
        agent: JobAgent,
    ) -> JobAgentSessionResponse:
        """加载上下文、执行 Agent，并在成功后保存本轮短期记忆。"""
        await self._session_store.ensure_session(
            session_id=request.session_id,
            user_id=user_id,
        )
        history = await self._conversation_memory.get_recent(request.session_id)
        analysis_context = await self._analysis_cache.list_recent(request.session_id)
        if request.jd_text is None and not history and not analysis_context:
            raise AppException(
                "No conversation context; provide jd_text for the first turn",
                code=40007,
                status_code=400,
            )

        turn = await self._session_store.next_turn(request.session_id)
        result = await agent.chat(
            request,
            turn=turn,
            history=history,
            analysis_context=analysis_context,
        )
        await self._conversation_memory.append_turn(
            request.session_id,
            user=request.message,
            assistant=result.final_answer,
        )
        if result.analysis is not None and result.job is not None:
            await self._analysis_cache.append(
                request.session_id,
                {
                    "job": result.job.model_dump(mode="json"),
                    "analysis": result.analysis.model_dump(mode="json"),
                },
            )
        return result.model_copy(update={"history_turns": result.history_turns + 1})

    async def get_state(self, *, user_id: int, session_id: str) -> JobAgentSessionState:
        """校验会话归属后返回最近对话与分析上下文。"""
        await self._session_store.require_session(session_id=session_id, user_id=user_id)
        return JobAgentSessionState(
            session_id=session_id,
            messages=await self._conversation_memory.get_recent(session_id),
            recent_analyses=await self._analysis_cache.list_recent(session_id),
        )
