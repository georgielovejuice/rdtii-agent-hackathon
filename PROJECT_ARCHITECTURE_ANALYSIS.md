# RDTII Project Architecture and Stack Analysis

Generated: 2026-05-12  
Analyzed folders:

- `/home/engineerkim/Desktop/un-hackathon`
- `/home/engineerkim/Desktop/rdtii-agent`

## Executive Summary

This is an AI-assisted regulatory analysis project for mapping national digital trade laws to the RDTII 2.0 framework, focused on Pillar 6, cross-border data policies, and Pillar 7, domestic data protection and privacy.

There are two related codebases:

1. `un-hackathon` is the earlier Streamlit application prototype. It provides a browser UI for downloading PDF legal documents, extracting text, mapping chunks to RDTII indicators with a local Hugging Face NLI cross-encoder, comparing countries, and showing a map.
2. `rdtii-agent` is the fuller production-style pipeline. It is CLI-first, audit-oriented, and designed around source authority tiers, structured extraction, hybrid retrieval, constrained legal reasoning, quote verification, JSON-LD export, Markdown country briefs, SQLite audit logs, and human review queues.

The more complete system architecture lives in `rdtii-agent`. The Streamlit prototype can be understood as an interactive front end or earlier proof of concept for the same product idea.

## Product Goal

The project tries to reduce manual regulatory research effort by:

- Finding authoritative laws and regulations for a country.
- Extracting structured legal provisions from PDFs or HTML.
- Matching provisions to RDTII Pillar 6 and Pillar 7 indicators.
- Producing scores with exact evidence.
- Rejecting unsupported scores using a "No Quote, No Score" rule.
- Routing uncertain items to human review.
- Exporting machine-readable and human-readable outputs.

Target use case: UN ESCAP digital trade governance analysis for Asia-Pacific economies.

## Repository Inventory

### `un-hackathon`

Main files:

| Path | Role |
|---|---|
| `README.md` | User-facing description for the Streamlit RDTII analyzer. |
| `un-rdtii/app.py` | Streamlit UI, navigation, analysis workflow, comparison table, world map. |
| `un-rdtii/crawler.py` | Downloads country PDF sources and performs simple PDF link fallback discovery. |
| `un-rdtii/extractor.py` | Extracts text from PDFs with `pdfplumber`; falls back to Surya OCR when available. |
| `un-rdtii/mapper.py` | Maps text chunks to RDTII indicators using `sentence-transformers` `CrossEncoder`. |
| `un-rdtii/requirements.txt` | Streamlit prototype dependencies. |
| `readable.py` | Small OCR result reader script, unrelated to core RDTII flow. |
| `test-easyocr.py` | Small OCR experiment using EasyOCR, unrelated to core RDTII flow. |

Approximate code size from local line counts: 1,619 lines.

### `rdtii-agent`

Main files:

| Path | Role |
|---|---|
| `README.md` | Primary project documentation and quick start. |
| `CLAUDE.md` | Detailed architecture, hackathon plan, technical narrative, stack rationale. |
| `CODEX_PROMPTS.md` | Historical build prompts and implementation plan. |
| `main.py` | CLI entry point and six-stage orchestration. |
| `pipeline/discover.py` | Source seed database and authority tier classifier. |
| `pipeline/extract.py` | PDF/HTML extraction, article parsing, bundled demo legal text. |
| `pipeline/authority.py` | Authority resolution, scoreable source filtering, conflict detection. |
| `pipeline/retrieval.py` | Hybrid retrieval with ChromaDB embeddings and NetworkX cross-reference graph. |
| `pipeline/reason.py` | Rubric loading, constrained LLM calls, heuristic fallback, scoring model. |
| `pipeline/verify.py` | Span verification and anti-hallucination checks. |
| `pipeline/export.py` | JSON-LD, review queue, Markdown country brief, SQLite audit trail. |
| `rubrics/pillar6.json` | RDTII Pillar 6 scoring rubric. |
| `rubrics/pillar7.json` | RDTII Pillar 7 scoring rubric. |
| `templates/country_brief.md.j2` | Markdown country brief template. |
| `tests/test_pipeline.py` | Unit and offline end-to-end tests. |
| `demo/*/output/*` | Pre-generated demo outputs for Thailand, Vietnam, Singapore. |
| `outputs/*` | Locally generated output artifacts. |

Approximate code size from local line counts: 3,025 lines across core files.

Note: `rdtii-agent` also contains accidentally created literal brace directories such as `./{pipeline,rubrics,templates,demo`. They do not appear to be part of the active application.

## High-Level System Architecture

The full architecture in `rdtii-agent` is a six-stage pipeline:

```text
Country + Pillar Scope
        |
        v
Stage 1: Discovery
        |
        v
Stage 2: Extraction
        |
        v
Stage 3: Authority Resolution
        |
        v
Stage 4: Hybrid Retrieval + Knowledge Graph
        |
        v
Stage 5: Legal Reasoning Chain
        |
        v
Stage 6: Verified Output
```

### Stage 1: Discovery

Implemented in `pipeline/discover.py`.

Responsibilities:

- Holds seed source URLs for Thailand, Vietnam, and Singapore.
- Filters seed sources by requested pillars.
- Assigns authority tiers using regex rules over URL and title.
- Infers document type from URL or content type.

Authority tiers:

| Tier | Meaning | Scoreable |
|---|---|---|
| Tier 1 | Official legislation, gazettes, official law portals | Yes |
| Tier 2 | Amendments, implementing regulations, official regulatory instruments | Yes |
| Tier 3 | Guidelines, FAQs, explainers, reference material | No, locate-only |

Important detail: Scrapy, Playwright, language detection, and broader crawling are listed in the stack and requirements, but the current implemented discovery flow is mostly seed-based and rule-based.

### Stage 2: Extraction

Implemented in `pipeline/extract.py`.

Responsibilities:

- Routes PDF and HTML sources to the appropriate extractor.
- For PDFs, tries Docling first, then Surya OCR, then Tesseract.
- For HTML, uses `requests` and BeautifulSoup.
- Falls back to bundled demo text when downloads or extraction fail.
- Parses raw legal text into article or section chunks.
- Computes a SHA-256 hash over extracted text.

Article parsing recognizes patterns such as:

- `Section 28`
- `Article 26`
- `Dieu 25`
- Thai section markers.
- Russian article markers.
- `Art. 26`

This stage produces document dictionaries with source metadata and article chunks.

### Stage 3: Authority Resolution

Implemented in `pipeline/authority.py`.

Responsibilities:

- Converts raw extracted documents into `AuthorityResolvedDoc` objects.
- Blocks Tier 3 sources from scoring.
- Keeps Tier 1 and Tier 2 sources scoreable.
- Detects simple conflicts when multiple scoreable documents contain the same section ID but materially different text length.
- Flags conflicts for human review.

Current conflict detection is intentionally simple. It uses same section ID plus length differences as a proxy, so it is useful for demos but not yet a full legal version reconciler.

### Stage 4: Hybrid Retrieval and Knowledge Graph

Implemented in `pipeline/retrieval.py`.

Responsibilities:

- Builds a ChromaDB vector index over extracted article chunks.
- Uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` embeddings.
- Falls back to keyword overlap if ChromaDB or embeddings are unavailable.
- Builds a NetworkX directed graph of article cross-references.
- Expands retrieval context by following references such as `Section X` or `Article X`.

Retrieval output is a `RetrievedContext` containing:

- Top semantic or keyword articles.
- Cross-reference articles.
- Combined article context used by the scoring stage.

### Stage 5: Legal Reasoning Chain

Implemented in `pipeline/reason.py`.

Responsibilities:

- Loads RDTII rubric JSON files.
- Builds constrained prompts per indicator and article.
- Calls an LLM backend when available.
- Falls back to deterministic heuristic classification when the LLM is unavailable.
- Enforces "No Quote, No Score".
- Sends every quote through span verification before accepting a score.

Supported LLM backends:

| Backend | Configuration | Notes |
|---|---|---|
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL=llama3.1:8b` | Only supported LLM backend in current code. |
| Heuristic | Automatic fallback | Uses exact phrase rules and returns `UNCERTAIN` if no quoteable evidence is found. |

Scoring output model: `ScoredIndicator`.

Key fields:

- Pillar number.
- Indicator ID and name.
- Numeric score.
- Confidence: `HIGH`, `MEDIUM`, or `UNCERTAIN`.
- Verbatim quote.
- Source URL, title, tier, article reference, hash.
- Rationale.
- Human review flag and reason.

### Stage 4b/5 Verification: Span Verifier

Implemented in `pipeline/verify.py`.

Responsibilities:

- Verifies the LLM quote exists in the source text.
- First checks normalized exact match.
- Falls back to fuzzy matching with a similarity threshold of 0.85.
- Checks whether extracted entities, such as article references or years, are grounded in the source.
- Rejects ungrounded or missing quotes as `UNCERTAIN`.

This is the core anti-hallucination component.

### Stage 6: Verified Output

Implemented in `pipeline/export.py`.

Outputs:

| Output | Format | Purpose |
|---|---|---|
| RDTII dataset | JSON-LD | Machine-readable linked data style output. |
| Country brief | Markdown via Jinja2 | Human-readable summary for policy review. |
| Human review queue | JSON | List of uncertain indicators needing expert review. |
| Audit trail | SQLite | Logs stage actions and decisions by run ID. |

Default output locations:

- `./outputs/{country}_rdtii_dataset.jsonld`
- `./outputs/{country}_country_brief.md`
- `./outputs/{country}_review_queue.json`
- `./outputs/audit/runs.sqlite`

## Streamlit Prototype Architecture

The `un-hackathon/un-rdtii` project is a UI-centered version of the same idea.

```text
Streamlit UI
    |
    +-- Document Discovery
    |       |
    |       +-- crawler.py downloads known PDFs
    |
    +-- Analysis
    |       |
    |       +-- extractor.py extracts and chunks PDF text
    |       +-- mapper.py maps chunks to indicators with CrossEncoder NLI
    |
    +-- Comparison Table
    |       |
    |       +-- shows country-by-indicator match levels
    |
    +-- World Map
            |
            +-- pydeck scatter map with demo or analysis-derived rows
```

### Streamlit App Pages

| Page | Purpose |
|---|---|
| Home | Explains countries, RDTII purpose, and workflow. |
| Document Discovery | Downloads known PDFs for Thailand, Vietnam, Indonesia. |
| Analysis | Runs PDF extraction and indicator mapping for preset or uploaded PDFs. |
| Comparison Table | Shows side-by-side indicator matches and allows CSV/JSON download. |
| World Map | Shows highlighted countries using PyDeck map points. |

### Streamlit AI Mapping

Implemented in `un-rdtii/mapper.py`.

- Uses `sentence_transformers.CrossEncoder`.
- Model name: `cross-encoder/nli-distilroberta-base`.
- Scores each `(text chunk, indicator description)` pair.
- Converts NLI logits to entailment probability.
- Keeps confirmed matches above threshold `0.5`.
- Keeps top candidate evidence for human review.

Match levels:

| Level | Score Range |
|---|---|
| Primary | `>= 0.85` |
| Contextual | `>= 0.70` and `< 0.85` |
| Implicit | `>= 0.50` and `< 0.70` |
| No match | `< 0.50` |

Important inconsistency: the `un-hackathon` README mentions `facebook/bart-large-mnli`, but the actual mapper code uses `cross-encoder/nli-distilroberta-base`.

## Stack

### Language and Runtime

| Area | Tools |
|---|---|
| Language | Python 3.11+ in `rdtii-agent`; generic Python in `un-hackathon`. |
| CLI | `argparse`, custom orchestration in `main.py`. |
| UI | Streamlit in `un-hackathon`. |
| Environment | `python-dotenv` optional in `rdtii-agent`. |

### AI and Classification

| Area | Tools |
|---|---|
| Local/remote LLM | Ollama with `llama3.1:8b` on local machine or friend GPU over Tailscale. |
| Offline fallback | Deterministic heuristic classifier in `pipeline/reason.py`. |
| Streamlit NLI | `sentence-transformers` `CrossEncoder`, model `cross-encoder/nli-distilroberta-base`. |
| Embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. |
| Transformer dependencies | `transformers`, `torch`, `sentencepiece`, `sacremoses`. |

### Retrieval and Knowledge

| Area | Tools |
|---|---|
| Vector store | ChromaDB, with keyword fallback. |
| Knowledge graph | NetworkX. |
| Cross-reference logic | Regex-based section/article detection. |

### Document and Web Processing

| Area | Tools |
|---|---|
| PDF extraction in `rdtii-agent` | Docling, Surya OCR, Tesseract, PyMuPDF listed. |
| PDF extraction in `un-hackathon` | `pdfplumber`, `pdf2image`, Surya OCR optional. |
| OCR experiments | EasyOCR in `test-easyocr.py`, not part of core app. |
| HTML extraction | `requests`, BeautifulSoup, `lxml`. |
| Discovery stack listed | Scrapy and Playwright are dependencies, but the implemented discovery remains seed/rule based. |

### Data and Output

| Area | Tools |
|---|---|
| Machine-readable output | JSON-LD. |
| Human-readable output | Markdown country brief via Jinja2 template. |
| Audit | SQLite. |
| Review queue | JSON. |
| Streamlit exports | CSV and JSON downloads. |

### Testing and Dev

| Area | Tools |
|---|---|
| Tests | Pytest. |
| Async test dependency | `pytest-asyncio` listed. |
| Make targets | install, Ollama setup, run per country, run all, tests, clean. |
| Packaging | `pyproject.toml` with `rdtii-agent = "main:main_cli"` script entry. |

## RDTII Domain Model

### Pillar 6 Indicators

Defined in `rdtii-agent/rubrics/pillar6.json`.

| ID | Indicator |
|---|---|
| 6.1 | Ban and local processing requirements |
| 6.2 | Local storage requirements |
| 6.3 | Infrastructure requirements |
| 6.4 | Conditional flow regimes |
| 6.5 | Not in an agreement with binding commitments on data transfer |

### Pillar 7 Indicators

Defined in `rdtii-agent/rubrics/pillar7.json`.

| ID | Indicator |
|---|---|
| 7.1 | Lack of comprehensive legal framework for data protection |
| 7.2 | Minimum period of data retention requirements |
| 7.3 | Data Impact Assessment or Data Protection Officer requirements |
| 7.4 | Requirements to allow Government access to personal data |

Note: the Streamlit prototype uses a slightly different Pillar 7 list with five indicators, including "Lack of dedicated cybersecurity framework" and splitting retention/DPIA/government access differently. `rdtii-agent` appears to be the newer rubric source.

## Data Flow in `rdtii-agent`

1. User runs `python main.py --country thailand --pillars 6 7`.
2. `main.py` creates a run ID and loads seed sources from `pipeline/discover.py`.
3. Each source is extracted by `pipeline/extract.py`.
4. Raw text is parsed into articles or sections.
5. `pipeline/authority.py` blocks Tier 3 material and keeps Tier 1/2 material.
6. `pipeline/retrieval.py` indexes scoreable articles and retrieves candidate context for each indicator.
7. `pipeline/reason.py` scores each retrieved article against one rubric indicator.
8. `pipeline/verify.py` checks the quoted evidence.
9. `main.py` keeps the best score per indicator using confidence, review flag, and source tier.
10. `pipeline/export.py` writes JSON-LD, Markdown brief, review queue, and audit rows.

## Trust and Anti-Hallucination Design

The strongest design idea is that the system treats every score as an evidence-backed claim.

Rules implemented or documented:

- No quote means no score.
- No source means no output.
- Tier 3 sources cannot be used for scoring.
- Scores require verbatim source evidence.
- LLM output must be structured JSON.
- Quotes are verified against source text.
- Failed verification becomes `UNCERTAIN`.
- Uncertain items go to the human review queue.
- Audit records track pipeline stages and decisions.

This is a better fit for regulatory analysis than a generic chatbot/RAG system because it preserves traceability.

## Operating Modes

### Full Local LLM Mode

```bash
ollama serve
ollama pull llama3.1:8b
python main.py --country thailand --pillars 6 7
```

Uses local Ollama if available, then verifies quotes before accepting output.

### Cloud LLM Mode

Remote Ollama over Tailscale:

```bash
export OLLAMA_BASE_URL=http://FRIEND_TAILSCALE_IP:11434
export OLLAMA_MODEL=llama3.1:8b
python main.py --country thailand --pillars 6 7
```

### Offline Demo Mode

If the selected LLM backend is unavailable, the project falls back to exact-phrase heuristic scoring and bundled demo text.

This is important for hackathon demos because it allows the pipeline to run without network, API keys, or heavy document extraction dependencies.

### Streamlit UI Mode

```bash
cd /home/engineerkim/Desktop/un-hackathon/un-rdtii
streamlit run app.py
```

This runs the browser UI for PDF download, extraction, NLI mapping, comparison table, and map view.

## Countries Covered

### Streamlit Prototype

Defined in `un-rdtii/crawler.py`:

- Thailand: Personal Data Protection Act B.E. 2562.
- Vietnam: Decree 13 on Personal Data Protection.
- Indonesia: Government Regulation PP 71 2019.

### Full Agent

Defined in `pipeline/discover.py`:

- Thailand: PDPA, Royal Gazette, ETDA.
- Vietnam: Cybersecurity Law and Decree 13/2023.
- Singapore: PDPA 2012 and PDPC source.

The `rdtii-agent` demo outputs currently exist for Thailand, Vietnam, and Singapore.

## Relationship Between the Two Folders

| Concern | `un-hackathon` | `rdtii-agent` |
|---|---|---|
| Primary interface | Streamlit web app | CLI pipeline |
| Main countries | Thailand, Vietnam, Indonesia | Thailand, Vietnam, Singapore |
| Scoring method | NLI cross-encoder over text chunks | Constrained LLM or heuristic over retrieved articles |
| Trust controls | Confidence thresholds and candidate evidence | Authority tiers, quote verification, review queue, audit DB |
| Output | UI state, JSON files under `data/results`, CSV/JSON download | JSON-LD, Markdown brief, review queue JSON, SQLite audit |
| Architecture maturity | Prototype/demo UI | More complete backend architecture |
| Best role going forward | Front end shell or demo app | Backend source of truth |

Recommended interpretation: `rdtii-agent` should be treated as the core project, and `un-hackathon` can either be retired or refactored into a UI that calls the `rdtii-agent` pipeline.

## Current Implementation Status

Implemented and working in code:

- CLI orchestration with six stages.
- Seed-based source discovery for three countries.
- Authority tier classification.
- PDF and HTML extraction paths with fallback demo text.
- Article/section parser.
- ChromaDB semantic retrieval with keyword fallback.
- NetworkX cross-reference graph.
- RDTII rubrics as JSON.
- Constrained prompts for LLM scoring.
- Ollama, OpenAI, and Anthropic backend selection.
- Offline heuristic scoring.
- Span verification.
- JSON-LD export.
- Markdown brief export.
- JSON review queue.
- SQLite audit logging.
- Pytest coverage for major trust controls and offline Thailand end-to-end flow.
- Streamlit UI prototype with download, analysis, comparison, and map views.

Partially implemented or mostly documented:

- Broad web crawling with Scrapy/Playwright.
- Language detection using `langdetect` or `fasttext`.
- Translation using Helsinki-NLP/OPUS-MT.
- Full legal version reconciliation.
- Full relation-preservation checking beyond quote/entity grounding.
- PDF export from Markdown via WeasyPrint.
- Streamlit integration with the newer `rdtii-agent` backend.

## Notable Gaps and Risks

1. The two projects use different country sets.
   - Streamlit: Thailand, Vietnam, Indonesia.
   - Agent: Thailand, Vietnam, Singapore.

2. The two projects use different indicator definitions.
   - Streamlit has 10 indicators, five for Pillar 6 and five for Pillar 7.
   - Agent has five Pillar 6 indicators and four Pillar 7 indicators.

3. The Streamlit README and code disagree on the NLI model.
   - README says `facebook/bart-large-mnli`.
   - Code uses `cross-encoder/nli-distilroberta-base`.

4. Some dependencies are aspirational or optional.
   - Scrapy, Playwright, language detection, translation, and WeasyPrint are listed, but not fully wired into the active pipeline.

5. The full pipeline has demo fallbacks.
   - This is good for reliable demos, but production claims must clearly separate extracted live source text from bundled sample text.

6. Conflict resolution is simple.
   - Current detection is based on duplicate section IDs and length differences. A production system needs date/version rules and semantic comparison.

7. The Streamlit app does not enforce the full trust model.
   - It has confidence thresholds and review candidates, but it does not implement source tier blocking, JSON-LD citations, SQLite audit, or span verification.

8. Literal brace directories exist in `rdtii-agent`.
   - These look accidental and should be removed after confirming they contain no needed files.

## Recommended Next Steps

1. Pick `rdtii-agent` as the backend source of truth.
2. Decide the final demo country set: Thailand, Vietnam, Singapore, or Thailand, Vietnam, Indonesia.
3. Align Pillar 7 indicators between both apps.
4. Refactor the Streamlit app to call `rdtii-agent.run_pipeline()` or shared service functions instead of maintaining separate mapper logic.
5. Add a clear flag in outputs showing whether evidence came from live extraction or bundled fallback text.
6. Replace simple conflict detection with version-aware authority resolution.
7. Remove accidental brace directories from `rdtii-agent` after inspection.
8. Add tests for Vietnam and Singapore end-to-end offline runs, not only Thailand.
9. Add tests for JSON-LD shape and audit DB contents.
10. Update documentation so model names, countries, and rubrics are consistent.

## Suggested Final Architecture

```text
                  Optional Streamlit UI
                         |
                         v
                 rdtii-agent service API
                         |
                         v
       +-----------------+-----------------+
       |                                   |
  CLI runner                         Batch runner
       |                                   |
       +-----------------+-----------------+
                         |
                         v
              Six-stage verified pipeline
                         |
                         v
       JSON-LD + Markdown brief + review queue + audit DB
```

This would keep one scoring engine, one trust model, one rubric source, and multiple user interfaces.

## Key Commands

Install and run the full agent:

```bash
cd /home/engineerkim/Desktop/rdtii-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --country thailand --pillars 6 7
```

Run all demo countries:

```bash
cd /home/engineerkim/Desktop/rdtii-agent
make run-all
```

Run tests:

```bash
cd /home/engineerkim/Desktop/rdtii-agent
pytest tests/ -v
```

Run the Streamlit prototype:

```bash
cd /home/engineerkim/Desktop/un-hackathon/un-rdtii
streamlit run app.py
```

## Bottom Line

The core project is not just an AI document classifier. The stronger architecture is an auditable legal evidence pipeline:

- Source discovery and authority ranking.
- Structured document extraction.
- Retrieval with semantic and cross-reference context.
- Rubric-constrained classification.
- Quote verification.
- Human review for uncertainty.
- Reproducible outputs and audit logs.

For a hackathon submission, the strongest story is `rdtii-agent` as the verified backend, with the Streamlit app as a possible visual demo layer.
