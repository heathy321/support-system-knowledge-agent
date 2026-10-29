"""Reviewed, read-only support checks. Code matches alone never authorize advice."""
import hashlib
import re

from app.models import AgentStep, AskResponse, Claim, GenerationInfo
from app.conversation import MAX_USER_TURNS

PLAYBOOK = 'osticket-api-create-401-v1'
PINNED_COMMIT = '8d38b0619649a50ee7cbbf37085f5d297fdc6f36'
# Digests of the complete, reviewed excerpts, not keyword matches. A new code
# revision or changed snippet requires review before this playbook can apply.
REVIEWED = {
    'include/class.api.php': ('requireApiKey', '27afe37af096333fd33f0541fec0970d7b9d0090a63f5f26cd013b85e5deede2'),
    'include/api.tickets.php': ('create', '1c25da8f690489de192e1ec1be3d33620f05b9e8c39373270fa4242a347aefc4'),
}
FOLLOW_UP = (
    'What is the exact error message, and which checks below have you completed? '
    'Report whether the problem persists or is resolved. If you cannot inspect a setting, say so. '
    'Do not include API keys, request bodies or customer information.'
)


def add_support_checks(request, result, retrieved_sources):
    """Add only approved checks whose full evidence survived retrieval."""
    q = request.question.lower()
    if (result.status != 'answered' or result.mode != 'static_code_analysis'
            or request.file_path or request.task != 'auto'
            or not re.search(r'\b401\b', q) or not re.search(r'\bapi\b', q)
            or not re.search(r'\bcreat(?:e|es|ed|ing)\b.{0,40}\btickets?\b', q)
            or re.search(r'\b(function|source code|locate|implementation)\b', q)):
        return
    reviewed = {}
    for source in retrieved_sources:
        if source.evidence_kind != 'code_excerpt' or source.file_path not in REVIEWED:
            continue
        symbol, digest = REVIEWED[source.file_path]
        actual = hashlib.sha256(source.evidence.strip().replace('\r\n', '\n').encode()).hexdigest()
        if (source.commit_sha == PINNED_COMMIT and source.context_kind == 'complete_symbol'
                and source.symbol_name == symbol and actual == digest):
            reviewed[source.file_path] = source
    if set(reviewed) != set(REVIEWED):
        return
    auth = reviewed['include/class.api.php'].chunk_id
    create = reviewed['include/api.tickets.php'].chunk_id
    result.support_checks = [
        Claim(text='In the integration request configuration, check that an X-API-Key header is present. Inspect it only in your authorized tools; do not paste its value here.', citation_ids=[auth]),
        Claim(text='If you can view the API key settings, check that the key is active and that its allowed IP matches the source IP seen by osTicket. If either value is unavailable, report that instead of guessing.', citation_ids=[auth]),
        Claim(text='If you can view the API key permissions, check that creating tickets is allowed. Report a missing permission; these checks do not authorize changing settings.', citation_ids=[create]),
    ]
    known = {s.chunk_id for s in result.sources}
    result.sources.extend(s for s in reviewed.values() if s.chunk_id not in known)
    result.support_playbook = PLAYBOOK
    result.resolution = 'checks_available'
    result.follow_up_questions = [FOLLOW_UP]
    result.next_step = 'Start with these read-only checks if you have access. Reply with the results; an engineer is not yet required just because the evidence comes from code.'
    result.agent_trace.append(AgentStep(agent='Support System Agent', action='offer_support_checks',
        detail='Matched both reviewed code excerpts; offer read-only checks and retain context for the outcome'))
    if sum(m['role'] == 'user' for m in request._clarification_history) >= MAX_USER_TURNS:
        result.resolution = 'engineering_review'
        result.reason_code = 'support_followup_limit'
        result.follow_up_questions = []
        result.next_step = 'The conversation limit was reached before check results could be collected. Share the handoff with an engineer or start a new question summarizing the issue and check results.'


def continue_support_checks(request):
    """Interpret only replies to checks actually offered by this server.

    This small deterministic outcome vocabulary is deliberately conservative.
    Ambiguous replies ask again; user reports never prove a production fix.
    """
    if not request._support_context:
        return None
    result = AskResponse.model_validate(request._support_context)
    if result.support_playbook != PLAYBOOK:
        return None
    reply = request._clarification_history[-1]['content'].strip().lower()
    result.agent_trace = [AgentStep(agent='Support System Agent', action='review_check_outcome',
        detail='Use the latest user report and previously reviewed evidence; no new retrieval or model request')]
    result.generation = GenerationInfo()
    result.intent_generation = GenerationInfo()
    result.handoff = None
    result.request_id = ''
    result.clarifying_questions = []
    result.reason_code = 'support_checks_pending'
    result.message = 'Waiting for the results of the read-only checks.'
    # Whole-message acknowledgements prevent quoted errors or negated success
    # ("not fixed") from accidentally closing an incident.
    resolved = re.fullmatch(r'(?:thanks[,! ]+)?(?:it works now|it is working now|the issue is resolved|the problem is resolved|resolved|fixed)[.! ]*', reply)
    requested = re.fullmatch(r'(?:please )?(?:escalate(?: this)?|hand (?:this|it) (?:over )?to an engineer|i need an engineer)[.! ]*', reply)
    denied = re.search(r"\b(?:i|we) (?:cannot|can't|do not have|don't have|lack) (?:the |admin |administrator )?(?:access|permission|permissions|view|inspect)\b", reply)
    checked = re.search(r'\b(?:i|we) (?:have )?(?:checked|verified|completed|tried) (?:all\b|(?:the|these) (?:three )?checks\b)|\ball (?:three )?checks (?:are )?(?:done|completed|passed)\b', reply)
    failed = re.search(r"\b(?:still (?:fails?|failing|get|getting|returns?|see|occurs?|not working)|problem persists|issue persists|same (?:401|error))\b", reply)
    hypothetical = re.search(r'\b(?:if|suppose|hypothetically)\b', reply)
    if hypothetical:
        denied = checked = None
    turns = sum(m['role'] == 'user' for m in request._clarification_history)
    if resolved:
        result.resolution = 'resolved_reported'
        result.reason_code = 'user_reported_resolution'
        result.message = 'The user reports that the issue is resolved.'
        result.answer = 'You reported that the issue is resolved. This assistant has not verified the live system or confirmed a root cause.'
        result.claims, result.sources, result.support_checks, result.follow_up_questions = [], [], [], []
        result.next_step = 'This support conversation is complete. Choose New question for another issue.'
    elif requested or denied or (checked and failed) or turns >= MAX_USER_TURNS:
        result.resolution = 'engineering_review'
        result.reason_code = ('support_access_required' if denied else 'support_escalation_requested' if requested
                              else 'support_checks_unsuccessful' if checked and failed else 'support_followup_limit')
        result.message = 'The available checks have not resolved the issue or require additional access.'
        result.next_step = ('Ask the osTicket administrator or integration owner to inspect the settings you cannot access. Share the handoff if engineering help is needed.' if denied else
                            'Share the handoff with an engineer, including the check results and exact error. No root cause or fix has been confirmed.')
        result.follow_up_questions = []
    else:
        result.resolution = 'checks_available'
        result.next_step = 'Reply with which checks you completed and their results, or say that you cannot access the settings. Use New question for a different issue.'
    return result
