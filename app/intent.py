"""Conservative, shared intent cues for offline routing and document topics.

Normalization is only for matching; questions, quotations, code identifiers and
stored evidence are never rewritten in responses or code-tool requests.
"""
import re
import unicodedata

DOC_CUES = ("documentation", "official", "configuration", "endpoint", "response")


def normalize(question: str) -> str:
    return unicodedata.normalize("NFKC", question).lower()


def required_fields_intent(question: str) -> bool:
    q = normalize(question)
    return bool(re.search(r"\b(fields?|parameters?|mandatory inputs?|required inputs?)\b", q)
                or re.search(r"\b(minimum|mandatory|required|necessary)\b.{0,30}\b(data|information|inputs?|details)\b", q)
                or re.search(r"\b(?:must(?:\s+(?:i|we|you))?|need to)\s+(provide|submit|send|supply|include)\b", q)
                or re.search(r"\bwhat (information|details)\b.{0,50}\b(need|collect|send|provide)\b", q))


def key_setup_intent(question: str) -> bool:
    q = normalize(question)
    key = bool(re.search(r"\b(?:api[ -]?)?keys?\b", q))
    operation = bool(re.search(r"\b(configure|configuration|create|enable|add|setup|set up|admin panel|management page)\b", q))
    return key and operation and not has_code_intent(question)


def has_doc_intent(question: str) -> bool:
    q = normalize(question)
    return (any(cue in q for cue in DOC_CUES)
            or bool(re.search(r"\b(documentation|docs?|configure|headers?|endpoints?)\b", q))
            or bool(re.search(r"\bhow (?:do i |to |can i )?(?:create|call|use)\b", q))
            or required_fields_intent(q) or key_setup_intent(q)
            or bool(re.search(r"\bapi\b", q) and re.search(r"\b(update|delete|modify|edit|change)\b.{0,30}\btickets?\b", q)))


def support_problem(question: str) -> bool:
    q = normalize(question)
    domain = re.search(r"\b(osticket|api|tickets?|login|log in|sign in|emails?|password)\b", q)
    failure = re.search(r"\b(cannot|can't|unable|failed|fails|failing|failure|error|denied|rejected|not working|not arriving|not receiving|doesn't work|won't)\b", q)
    return bool(domain and failure)


def has_code_intent(question: str, file_path: str | None = None) -> bool:
    q = normalize(question)
    if file_path:
        return True
    # "source IP" and "status code" are not requests for source code.
    prose = re.sub(r"\b(?:status|error|http) code\b", "", q)
    if re.search(r"\b(?:code|source code|repository|architecture|overview|structure|functions?|declarations?|implementation|logic|entry points?)\b", prose):
        return True
    if re.search(r"[a-z_./-]+\.(?:php|js|sql|md|txt|json)\b", q):
        return True
    # Recognize explicit camelCase / snake_case identifiers, but not the product name.
    identifiers = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", question)
    return any(word.lower() not in {"osticket", "apikey"} and
               (re.search(r"[a-z][A-Z]", word) or re.search(r"[a-z]_+[a-z]", word)) for word in identifiers)


def has_status_target(question: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9_.])[45]\d{2}(?![a-z0-9_.])", normalize(question)))


def needs_error_context(question: str, file_path: str | None = None) -> bool:
    """A bare HTTP error is not enough to select an incident workflow.

    Explicit code targets and named workflows remain searchable. This is a
    routing guard, not a claim that the supplied context establishes a cause.
    """
    if not has_status_target(question) or file_path:
        return False
    # "code 401" and "401 error code" describe an error, not source-code intent.
    prose = re.sub(r"\b([45]\d{2})\s+(?:(?:error|status|http)\s+)?code\b", r"\1", question, flags=re.I)
    prose = re.sub(r"\bcode\s+([45]\d{2})\b", r"\1", prose, flags=re.I)
    if has_code_intent(prose):
        return False
    q = normalize(question)
    workflow = re.search(r"\b(api|ajax|login|log[ -]in|sign[ -]in|staff panel|admin panel|customer portal)\b", q)
    ticket_action = re.search(r"\b(creat\w*|submit\w*|open\w*|updat\w*|delet\w*)\b.{0,35}\btickets?\b", q)
    return not (workflow or ticket_action)
