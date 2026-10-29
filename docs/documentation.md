# Official documentation corpus

The document branch contains six reviewed English summaries from three official osTicket v1.17.7 pages: API overview, ticket creation and API key management. The active corpus is `knowledge/osticket-docs.json`, version `osticket-api-docs-1.17.7-2026-10-28-en-v2`. Source metadata is also retained in `knowledge/osticket-doc-sources.json`.

| Topic ID | Coverage |
|---|---|
| `doc-auth` | X-API-Key header and source-IP requirement |
| `doc-key-setup` | Admin key configuration and Ticket Creation service |
| `doc-endpoint` | POST endpoints and request formats |
| `doc-fields` | Base required fields and custom-form caveat |
| `doc-response` | Success response and general failure description |
| `doc-capabilities` | Creation-only scope in this document version |

The summaries are curated paraphrases, not quotations. Source HTML was captured and reviewed on 2026-10-28 Japan time; UTC capture timestamps may show the previous day. Raw snapshots are in ignored `data/docs-snapshots/`. A page hash identifies captured bytes, not an immutable upstream URL. Versioned URLs can still change upstream.

The English migration translates the existing reviewed summaries without fetching newer policy or documentation. Source URLs, capture timestamps and HTML hashes remain unchanged. Corpus bytes and version change to identify the English wording. No equivalence between v1.17.7 documentation and the pinned code commit is assumed.

## Retrieval and refusal boundaries

English topic rules operate locally, with no query-time network access. Missing topics prompt clarification. Unsupported versions, attachment limits, rate limits, OAuth, proxy behavior and other uncovered dimensions return insufficient evidence. A related paragraph must not substitute for an answer to an unsupported question.

Combined retrieval runs document and code branches independently. Both must answer before a combined response can be answered; otherwise the result has branch statuses but no partial claims or sources. The subsequent optional generation stage can still abstain or fail.

## Maintenance

1. Select an approved official versioned page and capture its HTML.
2. Review the relevant sections and update English summaries, dates and source hashes consistently.
3. Update the corpus version. Runtime computes its SHA-256 from saved bytes.
4. Keep `osticket-doc-sources.json` aligned with the corpus sources.
5. Run document tests, English support regressions and combined-mode tests.

Corpus validation checks source URL allowlists, document version, unique IDs, complete topic coverage and source references. Failure returns `document_corpus_unavailable`. The source hash is provenance, not proof of semantic accuracy. Broader operator procedures are not covered.

See [English validation](intent-validation.md) for current development cases and [history](history.md) for preserved pre-English acceptance results.
