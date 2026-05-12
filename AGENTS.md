# AGENTS.md - RDTII Agent Working Notes

Last updated: 2026-05-12

This file is the persistent operating guide for coding agents working in this
repository. Every agent that edits this project must update this file in the
same turn, including the "Change Log" section.

## Required Agent Rule

- Before making changes, read this file plus any task-specific docs the user
  points to.
- After making any edit, update this file with:
  - Date.
  - Files changed.
  - What changed.
  - Verification run, or why verification was not run.
- Do not remove earlier change log entries unless the user explicitly asks.
- Do not overwrite user edits. If the working tree is dirty, inspect the
  relevant files and preserve unrelated changes.

## Project Goal

`rdtii-agent` is an AI-assisted regulatory analysis pipeline for mapping
national digital trade laws to the RDTII 2.0 framework, focused on:

- Pillar 6: Cross-border data policies.
- Pillar 7: Domestic data protection and privacy.

The core product promise is not generic RAG. The system must produce auditable
regulatory scores backed by exact legal evidence. The central rule is:

> No Quote -> No Score. No Tier 1/2 Source -> No Output.

## Source Documents Read

This file was created after reviewing:

- `CLAUDE.md`
- `CODEX_PROMPTS.md`
- `PROJECT_ARCHITECTURE_ANALYSIS.md`
- `message.txt`

## Current Strategic Direction

Treat `rdtii-agent` as the source-of-truth backend. It already contains the
more complete architecture:

1. Discovery.
2. Extraction.
3. Authority resolution.
4. Hybrid retrieval plus knowledge graph.
5. Legal reasoning chain.
6. Verified outputs.

Treat `/home/engineerkim/Desktop/un-hackathon` as a related Streamlit prototype
or future frontend reference. The architecture analysis says it is useful for
UI ideas, document download workflows, comparison tables, and map display, but
`rdtii-agent` has the stronger audit model and should drive scoring.

## Non-Negotiable Design Rules

- The LLM is a constrained classifier, not a free-form legal interpreter.
- Every confirmed score must include a verbatim quote, source title, source URL
  or file hash, authority tier, article or section reference, and source date
  when available.
- Tier 3 sources are reference-only. They may help locate provisions but must
  not be used for scoring.
- Unverified quotes become `UNCERTAIN` and go to human review.
- Conflict handling must preserve source hierarchy: Tier 1 wins over Tier 2,
  and conflicts should be logged for review.
- Offline/demo mode must keep working. Heuristic fallback must obey the same
  no-quote rule as LLM mode.
- Legal scoring should remain deterministic; use temperature 0 when supported.

## Current Implementation Snapshot

According to the reviewed docs, `rdtii-agent` currently includes:

- CLI orchestration in `main.py`.
- Seed-based discovery for Thailand, Vietnam, and Singapore.
- Extraction with PDF/HTML paths and bundled fallback legal text.
- Authority tier classification and scoreable filtering.
- ChromaDB/embedding retrieval with keyword fallback.
- NetworkX-based cross-reference graph.
- RDTII rubrics in JSON for Pillars 6 and 7.
- LLM backends for Ollama, OpenAI, Anthropic, plus heuristic fallback.
- Span verification in `pipeline/verify.py`.
- JSON-LD, Markdown country briefs, review queue JSON, and SQLite audit output.
- Pytest coverage for important no-quote, verifier, authority, and offline
  pipeline behavior.

Known gaps and priorities from the docs:

- Real PDF loading and reliable source ingestion remain important.
- Keyword pre-filtering and NLI pre-ranking are useful speed/quality upgrades.
- ChromaDB may be optional or unavailable, so fallback paths matter.
- Streamlit UI is a desired demo-day interface.
- Broader crawler automation and storage/indexing are part of the future plan.

## Friend Project / Team Conversation Takeaways

`message.txt` describes a related plan for a more automated ingestion and UI
stack:

- Search engine or API collects official government URLs.
- Crawler visits pages, extracts PDF links, downloads legal PDFs, then parses
  text.
- Cached results should bypass crawling on repeat runs.
- Supabase Storage or S3 can store original PDFs, OCR JSON, and extracted text.
- PostgreSQL can store country metadata, document metadata, chunks, citations,
  indicator matches, and confidence scores.
- `pgvector` can store embeddings for chunks.
- The user-facing analysis page should read from the database/index, not force
  users to manually download PDFs.
- The team discussed hybrid local/cloud AI provider switching, possibly using
  YAML config and a queue/service pattern.
- Language detection was discussed as a separate lightweight service, but that
  remains an idea rather than a required current implementation.

Practical interpretation: keep the current CLI pipeline stable while moving
toward automated ingestion, persistent storage, vector indexing, and a UI that
calls the backend rather than duplicating scoring logic.

## Suggested Next Build Priorities

1. Add or improve Streamlit UI around the existing `rdtii-agent` backend.
2. Strengthen automated discovery and PDF download for official government
   sources.
3. Persist documents, chunks, embeddings, citations, and scores in a database
   model compatible with future Supabase/PostgreSQL/pgvector use.
4. Add caching/staleness rules so repeat analyses avoid unnecessary crawling.
5. Improve extraction reliability for real PDFs and scanned documents.
6. Add keyword pre-filter and NLI pre-ranker where they reduce LLM calls.

## Key Commands

Run offline/demo pipeline:

```bash
python main.py --country thailand --pillars 6 7
python main.py --country vietnam --pillars 6 7
python main.py --country singapore --pillars 6 7
```

Run tests:

```bash
pytest tests/ -v
```

Use Makefile targets when available:

```bash
make run-thailand
make run-vietnam
make run-singapore
make run-all
make test
```

## Change Log

### 2026-05-12

Files changed:

- `main.py`
- `pipeline/authority.py`
- `pipeline/reason.py`
- `pipeline/export.py`
- `templates/country_brief.md.j2`
- `tests/test_pipeline.py`
- `AGENTS.md`

What changed:

- Added `extraction_method` provenance to the scoring metadata path.
- Preserved the extraction method from extracted documents through authority
  resolution, scoring, JSON-LD export, review queue export, and country briefs.
- Added test coverage that confirmed JSON-LD entries expose the provenance
  field for confirmed scores.
- Updated this required agent change log.

Verification:

- `pytest tests/ -v` -> 9 passed.
- `python -m json.tool outputs/thailand_rdtii_dataset.jsonld` -> valid JSON.
- Checked generated Thailand JSON-LD and Markdown brief include
  `extraction_method` / `Extraction Method`.

### 2026-05-12

Files changed:

- `AGENTS.md`

What changed:

- Created persistent agent guidance for the repository.
- Summarized the project direction from `CLAUDE.md`, `CODEX_PROMPTS.md`,
  `PROJECT_ARCHITECTURE_ANALYSIS.md`, and `message.txt`.
- Added the mandatory rule that future agents must update `AGENTS.md` whenever
  they edit this project.

Verification:

- Not run. Documentation-only change.
