# Third-party sources and attribution

This is an independent portfolio project, not an official osTicket product. It uses public sources to demonstrate evidence retrieval and support workflows.

## osTicket source code

- Repository: [osTicket/osTicket](https://github.com/osTicket/osTicket).
- Reviewed commit: `8d38b0619649a50ee7cbbf37085f5d297fdc6f36`.
- Upstream license text: [LICENSE.txt at the pinned commit](https://github.com/osTicket/osTicket/blob/8d38b0619649a50ee7cbbf37085f5d297fdc6f36/LICENSE.txt), headed GNU General Public License, Version 2, June 1991.
- Code excerpts retain upstream ownership. Citations link to the pinned file and line range. The reviewed API excerpts in `tests/test_support_checks.py` come from `include/class.api.php` and `include/api.tickets.php` at that commit.
- The full upstream clone and generated index are local setup outputs under ignored `data/`, not part of this project's Git file set. Screenshots and historical artifacts can show short cited excerpts.

## osTicket documentation

The corpus contains independently curated English summaries of three official v1.17.7 pages. These are paraphrases, not verbatim documentation or a claim of affiliation. Titles, URLs, retrieval timestamps and source hashes are retained in `knowledge/osticket-doc-sources.json` and `knowledge/osticket-docs.json`. See [corpus provenance and limitations](docs/documentation.md).

## Dependencies and project licensing

Python dependencies are listed in `requirements.lock` and retain their respective upstream licenses. No third-party package is vendored in this repository. A license for this project's original implementation has not yet been selected; these notices do not grant additional rights or relicense upstream material.

Archived materials in `docs/archive/` preserve earlier project evidence and are not current product documentation. Their original provenance and validation limits are retained.
