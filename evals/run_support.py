"""English document/routing development regressions. Historical suites are archived."""
import argparse
import hashlib
import json
from pathlib import Path

from app.agents.customer_support import CustomerSupportAgent
from app.agents.code_analyzer import CodeAnalyzerAgent
from app.models import AskRequest, CodeCitation, DocumentCitation
from app.main import VERSION

ROOT = Path(__file__).resolve().parent


def run(suite="dev", backend="local"):
    if suite != "dev":
        raise SystemExit("Pre-English acceptance suites are preserved in docs/archive/pre-english-v07.zip; only English development cases run here.")
    path=ROOT / f"docs_{suite}_cases.json"
    raw=path.read_bytes()
    cases=json.loads(raw)
    acceptance = suite.startswith("acceptance")
    output=ROOT / (f"docs-{suite.replace('_', '-')}-first.json" if acceptance else f"docs-{backend}-latest.json")
    if acceptance and output.exists():
        raise SystemExit("First acceptance report already exists; preserve it and use new cases for future acceptance.")
    agent=CustomerSupportAgent(CodeAnalyzerAgent(backend=backend))
    corpus,info=agent.documentation.load()
    index,index_hash=agent.code_analyzer.store.load()
    files={f.path:f.lines for f in index.files}
    summaries={c.id:c.summary for c in corpus.chunks}
    rows=[]
    for c in cases:
        r=agent.ask(AskRequest(answer_mode="offline", question=c['question'],task=c.get('task','auto'), product_version=c.get('product_version')))
        ids={s.chunk_id for s in r.sources}
        checks={'status':r.status==c['status'], 'route':r.mode==c['mode'], 'required_citations':set(c['required'])<=ids}
        checks['expected_code'] = not c.get('code') or any(isinstance(s,CodeCitation) for s in r.sources)
        checks['citations']=all(
            (s.chunk_id in summaries and s.evidence==summaries[s.chunk_id] and s.document_version==info.document_version)
            if isinstance(s,DocumentCitation) else
            (s.file_path in files and s.evidence=='\n'.join(files[s.file_path][s.line_start-1:s.line_end]) and s.commit_sha==index.commit_sha)
            for s in r.sources)
        if 'reason' in c: checks['reason'] = r.reason_code == c['reason']
        checks['claims']=all(claim.citation_ids and set(claim.citation_ids)<=ids for claim in r.claims)
        checks['bounded_answer']=bool(r.sources) if r.status=='answered' else r.answer is None and not r.sources
        checks['version_boundary']=r.mode in {'static_code_analysis', 'routing'} or (bool(r.warnings) and r.documentation is not None and r.documentation.code_version_relation=='unverified')
        rows.append({'id':c['id'],'status':r.status,'mode':r.mode,'reason':r.reason_code,'passed':all(checks.values()),'checks':checks,'citation_ids':sorted(ids)})
    report={'app_version':VERSION,'suite':suite,'backend':backend,'cases_sha256':hashlib.sha256(raw).hexdigest(),
        'documentation':info.model_dump(),'code_commit':index.commit_sha,'code_index_sha256':index_hash,
        'cases':len(rows),'passed':sum(r['passed'] for r in rows),'results':rows,
        'limitations':'English adaptations of same-author development cases; not independent or blind evaluation. Inputs and corpus differ from pre-English reports, which remain archived. Exact summary identity does not measure semantic entailment.'}
    with output.open('x' if acceptance else 'w',encoding='utf-8') as f:
        f.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('suite','backend','cases','passed')},ensure_ascii=False))
    print('Failed cases:', [r['id'] for r in rows if not r['passed']])
    return 0 if report['passed']==report['cases'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['dev'],default='dev')
    parser.add_argument('--backend',choices=['local','mcp_stdio'],default='local')
    args=parser.parse_args()
    raise SystemExit(run(args.suite,args.backend))
