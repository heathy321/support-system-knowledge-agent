"""English output and active-project localization regressions."""
from pathlib import Path
import re

import pytest

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.models import AskRequest
from test_code_agents import store

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


@pytest.mark.parametrize('question,kwargs,status', [
    ('Which fields are required to create a ticket through the API?', {}, 'answered'),
    ('Which code should I inspect when the osTicket API returns 401?', {}, 'answered'),
    ('What authentication header does the documentation require? Locate the requireApiKey function as well.', {}, 'answered'),
    ('Help me with the osTicket API', {}, 'needs_clarification'),
    ('What fields are required for API tickets?', {'product_version':'1.18.2'}, 'insufficient_evidence'),
    ('Official API attachment limits', {}, 'insufficient_evidence'),
    ('API required fields', {'answer_mode':'gemini'}, 'upstream_error'),
])
def test_response_paths_use_english(store, monkeypatch, question, kwargs, status):
    monkeypatch.delenv('ENABLE_GEMINI',raising=False)
    agent=CustomerSupportAgent(CodeAnalyzerAgent(store))
    r=agent.ask(AskRequest(question=question,**kwargs))
    assert r.status==status
    assert r.agent=='Support System Agent'
    assert not CJK.search(r.model_dump_json())


def test_active_project_text_has_no_untranslated_chinese():
    root=Path(__file__).resolve().parents[1]
    suffixes={'.py','.js','.html','.css','.md','.json','.toml','.ps1','.yml'}
    paths=[p for folder in ('app','tests','scripts','knowledge','evals','docs','.github')
           for p in (root/folder).rglob('*') if p.is_file() and p.suffix in suffixes]
    paths += [root/'README.md',root/'pyproject.toml',root/'.env.example']
    leftovers=[str(p.relative_to(root)) for p in paths if CJK.search(p.read_text(encoding='utf-8')) or CJK.search(p.name)]
    assert not leftovers, f'Untranslated active files: {leftovers}'
