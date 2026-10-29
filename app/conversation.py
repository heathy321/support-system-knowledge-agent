"""Bounded, process-local memory for pending clarifications, never answer evidence."""
from dataclasses import dataclass
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from uuid import uuid4

from app.models import AgentStep, AskRequest, AskResponse, ConversationInfo

MAX_USER_TURNS = 4
MAX_CONTEXT_CHARS = 6000
TTL_SECONDS = 900
MAX_PENDING = 128
OPTIONS = ('task', 'repository', 'file_path', 'product_version', 'answer_mode')


@dataclass
class Pending:
    original: AskRequest
    turns: list[str]
    history: list[dict]
    expires_at: float
    busy: bool = False
    support_context: dict | None = None


class ClarificationMemory:
    def __init__(self, ttl=TTL_SECONDS, capacity=MAX_PENDING, clock=monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self._pending = {}
        self._lock = Lock()

    def _prune(self):
        now = self.clock()
        for key in list(self._pending):
            entry = self._pending[key]
            if not entry.busy and entry.expires_at <= now:
                del self._pending[key]

    def reset(self, token):
        with self._lock:
            self._prune()
            self._pending.pop(token, None)

    def _problem(self, reason, message, state='expired', token=None, turns=1):
        return AskResponse(status='upstream_error' if state == 'busy' else 'needs_clarification',
            reason_code=reason, message=message, mode='routing', request_id=str(uuid4()),
            scope='Conversation state only. No retrieval or model call was performed.',
            clarifying_questions=[] if state == 'busy' else [message],
            next_step=message, resolution='clarification_needed', retryable=state == 'busy',
            conversation=ConversationInfo(state=state, clarification_id=token, user_turns=turns),
            agent_trace=[AgentStep(agent='Support System Agent', action='check_clarification_context', detail=reason)])

    @staticmethod
    def _question(turns):
        # Search only the user's words. Labels such as "original question" can
        # otherwise consume the lexical search budget and become false matches.
        return '\n'.join(turns)

    def ask(self, request, assistant):
        token = request.clarification_id
        entry = None
        with self._lock:
            self._prune()
            if token:
                entry = self._pending.get(token)
                if entry is None:
                    return self._problem('conversation_expired', 'This conversation expired or was cleared. Start a new question with the relevant details.')
                if entry.busy:
                    return self._problem('conversation_busy', 'A reply is already being processed. Wait for it to finish.', 'busy', token, len(entry.turns))
                if any(key in request.model_fields_set and getattr(request, key) != getattr(entry.original, key) for key in OPTIONS):
                    return self._problem('conversation_options_changed', 'Start a new question to change the request settings.', 'retry', token, len(entry.turns))
                turns = entry.turns + [request.question]
                if len(turns) > MAX_USER_TURNS or len(self._question(turns)) > MAX_CONTEXT_CHARS:
                    del self._pending[token]
                    return self._problem('conversation_limit_reached', 'The conversation limit was reached. Start a new question summarizing the relevant details.', 'limit_reached', turns=len(entry.turns))
                entry.busy = True
                entry.expires_at = self.clock() + self.ttl
                # Internal composed question has a separate bounded budget. Public
                # individual messages still undergo AskRequest's 1500-char validation.
                effective = entry.original.model_copy(update={'question': self._question(turns), 'clarification_id': None})
                effective._clarification_history = entry.history + [{'role': 'user', 'content': request.question}]
                effective._support_context = entry.support_context
            else:
                turns = [request.question]
                effective = request
        try:
            result = assistant.ask(effective)
        except Exception:
            with self._lock:
                if entry is not None and self._pending.get(token) is entry:
                    entry.busy = False
            raise
        if entry:
            result.agent_trace.insert(0, AgentStep(agent='Support System Agent', action='restore_clarification_context',
                detail=f'Use {len(turns)} user messages from the pending clarification; previous answers are not evidence'))
            if result.handoff:
                result.handoff['user_messages'] = turns
        with self._lock:
            self._prune()
            active = entry is None or self._pending.get(token) is entry
            if entry and active and result.status == 'upstream_error':
                entry.busy = False
                result.conversation = ConversationInfo(state='retry', clarification_id=token,
                    user_turns=len(entry.turns), expires_in_seconds=max(0, int(entry.expires_at-self.clock())), context_used=True)
                result.next_step = 'The request failed. Your earlier context is retained temporarily; retry or edit this reply. No automatic retry was made.'
                return result
            if entry and active:
                del self._pending[token]
            result.conversation = ConversationInfo(user_turns=len(turns), context_used=entry is not None)
            if result.status == 'needs_clarification' or result.resolution == 'checks_available':
                if not active:
                    result.conversation.state = 'expired'
                    result.next_step = 'This conversation was cleared while processing. Start a new question with the relevant details.'
                elif len(turns) >= MAX_USER_TURNS or len(self._question(turns)) >= MAX_CONTEXT_CHARS:
                    result.conversation.state = 'limit_reached'
                    result.next_step = 'The conversation limit was reached. Start a new question summarizing the relevant details.'
                elif len(self._pending) >= self.capacity:
                    result.conversation.state = 'unavailable'
                    result.next_step = 'Conversation memory is full. Submit the original question together with your additional details.'
                else:
                    next_token = token_urlsafe(32)
                    history = (entry.history if entry else []) + [
                        {'role': 'user', 'content': request.question},
                        {'role': 'assistant', 'content': '\n'.join(
                            [c.text for c in result.support_checks] + result.follow_up_questions + result.clarifying_questions)}]
                    support_context = result.model_dump() if result.resolution == 'checks_available' else None
                    self._pending[next_token] = Pending(entry.original if entry else request, turns, history, self.clock()+self.ttl,
                                                       support_context=support_context)
                    result.conversation = ConversationInfo(state='awaiting_reply', clarification_id=next_token,
                        user_turns=len(turns), expires_in_seconds=self.ttl, context_used=entry is not None)
                    result.next_step = ('Review the read-only checks below, then reply with the results and exact error. Do not share secrets. Your original question is retained temporarily. Choose New question to change topics.'
                                        if result.resolution == 'checks_available' else
                                        'Reply with the missing details below. Your original question is retained temporarily. Choose New question to change topics.')
        return result
