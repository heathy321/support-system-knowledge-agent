"""客服协助代理 routes domain requests and calls the code-analyzer subagent."""
import logging
import re
from time import perf_counter
from uuid import uuid4

from app.agents.code_analyzer import CodeAnalysisTask, CodeAnalyzerAgent
from app.agents.repository import REPOSITORY_URL
from app.models import AgentStep, AskRequest, AskResponse
from app.service import KnowledgeAssistant

logger = logging.getLogger("travel_ops")


class CustomerSupportAgent:
    name = "客服协助代理"

    def __init__(self, policy: KnowledgeAssistant | None = None, code_analyzer: CodeAnalyzerAgent | None = None):
        self.policy = policy or KnowledgeAssistant()
        self.code_analyzer = code_analyzer or CodeAnalyzerAgent()

    @property
    def store(self):
        return self.policy.store

    def today(self):
        return self.policy.today()

    def ask(self, request: AskRequest) -> AskResponse:
        started = perf_counter()
        q = request.question.lower()
        code_requested = request.task == "code_analysis" or (request.task == "auto" and (
            request.repository is not None or request.file_path is not None or
            any(word in q for word in ("osticket", "代码分析器", "代码仓库", "源码", "仓库结构", "github.com/")) or
            bool(re.search(r"[a-z_/]+\.(?:php|js|sql)\b", q))))
        if code_requested:
            task = CodeAnalysisTask(question=request.question, repository=request.repository or REPOSITORY_URL, file_path=request.file_path)
            result = self.code_analyzer.run(task)
            result.agent_trace.insert(0, AgentStep(agent=self.name, action="delegate_code_analysis", detail="将代码问题委派给代码分析器"))
            result.agent_trace.append(AgentStep(agent=self.name, action="return_result", detail="接收子代理结果并返回统一状态与引用"))
            result.context = request.context
        else:
            result = self.policy.ask(request)
            result.agent_trace = [AgentStep(agent=self.name, action="query_travel_policy", detail="调用旅行政策检索流程")]
        result.agent = self.name
        result.request_id = result.request_id or str(uuid4())
        result.latency_ms = round((perf_counter() - started) * 1000, 3)
        logger.info("request_id=%s agent=customer_support delegated=%s status=%s reason=%s latency_ms=%s",
                    result.request_id, bool(result.delegated_to), result.status, result.reason_code, result.latency_ms)
        return result
