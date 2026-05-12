# CLAUDE.md — RDTII Regulatory Intelligence Agent
## Hackathon: Global Hackathon on Using AI for Digital Trade Regulatory Analysis
## Submission Deadline: 15 May 2026 | Event: Paperless Trade Week, Bangkok, June 2026

---

## Project Vision

> Build an AI pipeline that replicates — and eventually surpasses — the work of a $2,000/country human regulatory researcher, starting with Pillar 6 (Cross-border Data Policies) and Pillar 7 (Domestic Data Policies) of the RDTII 2.0 framework.

**Our differentiator:** Not just a RAG pipeline. A **Legal Reasoning Chain** backed by a Hybrid RAG + Knowledge Graph architecture that produces auditable, conflict-resolved, span-verified, human-reviewable regulatory evidence — the way a lawyer argues a case, not the way a chatbot answers a question.

---

## Current Status (as of 10 May 2026)

### What is working
- Pipeline runs end-to-end for Thailand, Vietnam, Singapore (offline mode)
- Ollama backend wired — direct native HTTP API, default model configurable
- Remote GPU setup via Tailscale (friend's RTX 5070 12GB)
- "No Quote, No Score" rule enforced in both LLM and heuristic modes
- 3-tier source authority system with conflict detection
- SQLite audit trail, JSON-LD output, human review queue, country brief
- 9 pytest tests passing

### Current bottlenecks (in priority order)
1. Real PDF not loading — pipeline falls back to 6-section bundled text instead of 178-section real PDPA
2. Keyword pre-filter not yet added — LLM called ~150 times per run (slow)
3. ChromaDB not installed — semantic retrieval falls back to keyword overlap
4. No Streamlit UI — judges see terminal output only
5. NLI CrossEncoder pre-ranker not yet added

### LLM Backend
- Primary: Ollama on friend's RTX 5070 12GB via Tailscale
- Required model: llama3.1:8b
- Fallback: Local heuristic classifier (no GPU needed, all rules still apply)

---

## Why We Are Different From Every Other Team

| What others will do | What we do |
|---|---|
| LangChain + GPT-4 + plain vector search | Hybrid RAG + Knowledge Graph + span-level verification |
| Demo on 1 country, English only | Multi-source, multi-language, conflict resolution |
| Output: JSON blob | Output: Audit trail + confidence score + human review flag |
| Trust the LLM to interpret freely | Constrain LLM with hardcoded rubric — scores only what it can cite |
| General RAG pipeline | RDTII-specific scoring logic hardcoded as structured JSON rubric |
| Hallucination risk | "No Quote, No Score" rule + HalluGraph-style span verifier |
| No source hierarchy | 3-tier authority system: law > amendment > guideline |
| Citation-free scores | Verbatim quote + URL + article ref + SHA256 + date on every score |

---

## System Architecture (6 Stages)

```
INPUT: Country Name + Pillar Scope (6 and/or 7)
        │
        ▼
┌──────────────────────────────────────────────┐
│  STAGE 1: DISCOVERY                          │
│  - Scrapy + Playwright (JS-heavy gov sites)  │
│  - Source authority ranker (gov.XX = Tier 1) │
│  - Language detector (langdetect + fasttext) │
│  - file:// URL support for local PDFs        │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│  STAGE 2: EXTRACTION                         │
│  - Docling          → digital PDFs (primary) │
│  - Surya OCR        → scanned PDFs (primary) │
│  - Tesseract        → scanned PDFs (fallback)│
│  - Playwright + BS4 → HTML pages             │
│  - Structure parser → article/section/clause │
│  - Bundled demo text → offline fallback      │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│  STAGE 3: AUTHORITY RESOLUTION  ★            │
│  - Tier 1: Official legislation / gazette    │
│  - Tier 2: Amendments / implementing regs    │
│  - Tier 3: Guidelines — locate only, no score│
│  - Conflict detector + version reconciler    │
│  - Tier 1 always wins; conflict → human queue│
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│  STAGE 4: HYBRID RAG + KNOWLEDGE GRAPH  ★    │
│  - ChromaDB (local) → semantic retrieval     │
│  - NLI CrossEncoder → pre-ranker fallback    │
│  - NetworkX KG      → cross-ref tracking     │
│  - Span verifier    → claim ↔ source match   │
│    (HalluGraph-style: Entity Grounding +     │
│     Relation Preservation check)             │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│  STAGE 5: LEGAL REASONING CHAIN  ★           │
│  - Keyword pre-filter (skip irrelevant)      │
│  - RDTII rubric loader (Pillar 6+7 JSON)     │
│  - Constrained LLM via Ollama (remote GPU)   │
│    → classify only, never freestyle          │
│  - Conflict resolver (Tier 1 wins)           │
│  - Confidence: HIGH / MEDIUM / UNCERTAIN     │
│  - UNCERTAIN → auto-routed to human queue    │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│  STAGE 6: VERIFIED OUTPUT                    │
│  - JSON-LD dataset (score + citation)        │
│  - Country brief (Jinja2 → Markdown/PDF)     │
│  - SQLite audit trail (every decision logged)│
│  - Human review queue (uncertain items)      │
│  - Streamlit web UI (demo day interface)     │
└──────────────────────────────────────────────┘

RULE: No quote → No score. No source → No output.
```

---

## The Legal Reasoning Chain (Core Innovation)

Instead of asking the LLM: *"Does this text relate to Pillar 6?"*

We ask: *"Given RDTII Pillar 6, Indicator: Ban & local processing requirements, and the following legal text from Article 26 of Vietnam's Cybersecurity Law, does this provision impose, partially impose, or not impose a data localization requirement? You must quote the exact phrase from the provided text that supports your answer. If you cannot find a supporting phrase, return UNCERTAIN."*

**The LLM is a classifier constrained by a rubric. Not a free-form interpreter.**

### What the LLM IS allowed to do
- Classify a provision against a specific RDTII indicator
- Extract the exact verbatim phrase that supports its classification
- Identify linguistic ambiguity between provisions
- Flag conflicts between sources for human review
- Return UNCERTAIN when evidence is insufficient

### What the LLM IS NOT allowed to do
- Score an indicator without an exact verbatim citation
- Infer regulatory intent beyond what is explicitly written
- Combine multiple sources to create a synthesized interpretation
- Use Tier 3 sources (guidelines, FAQs) as evidence for scoring
- Output any score above UNCERTAIN confidence without a traceable quote

---

## Source Authority Hierarchy

```
TIER 1 — Authoritative (used for scoring)
  Official legislation (Acts, Laws, Decrees, Ordinances)
  Official government gazette publications

TIER 2 — Supplementary (used for scoring with flag)
  Regulatory amendments
  Official implementing regulations
  Ministerial orders with legal force

TIER 3 — Reference only (NEVER used for scoring)
  Ministry guidelines and FAQs
  Government explanatory notes
  Unofficial paraphrases or summaries
```

---

## Anti-Hallucination Design

### The "No Quote, No Score" Rule
Every RDTII indicator score must include ALL of:
- Exact verbatim quoted text (not paraphrased)
- Source name + authority tier
- Article / Section / Page reference
- URL or document SHA256 hash
- Date of the source document

If any of these are missing → score rejected → human review queue.

### Span-Level Verification (HalluGraph-inspired)
After LLM produces a classification + quote:
1. Extract entities from the quote (law names, article numbers, dates)
2. Check each entity exists verbatim in source (Entity Grounding check)
3. Check relationship asserted is supported by source (Relation Preservation check)
4. If either fails → UNCERTAIN → human queue

### Key Failure Cases We Catch
**The Paraphrase Trap:** Tier 3 guideline says "data must stay local." Tier 1 law says "transfers require authorization." System scores only from Tier 1, logs Tier 3 as "located but not used."

**The Linguistic Conflict Trap:** "Shall not transfer" (primary rule) vs "except in accordance with requirements" (exception clause). System scores each separately. Never blends them into one synthesized score.

---

## Full Tech Stack

### Core
| Component | Tool | Reason |
|---|---|---|
| Language | Python 3.11+ | Ecosystem depth, UN-friendly |
| Orchestration | Custom pipeline | No LangChain — too opaque for UN auditors |
| LLM (primary) | Ollama on remote RTX 5070 via Tailscale | Free, no quota, private network |
| LLM model | llama3.1:8b | Only supported LLM model for the demo |
| LLM (offline fallback) | Local heuristic classifier | Fully air-gapped, all rules still apply |
| License | MIT open-source | Required by hackathon |

### Document Extraction
| Component | Tool | Reason |
|---|---|---|
| Digital PDF | Docling (IBM Research) | 97.9% table accuracy, preserves legal structure |
| Local PDF | file:// URL handler | Reads downloaded PDFs directly from disk |
| Scanned PDF (primary) | Surya OCR | 90+ languages, open-source |
| Scanned PDF (fallback) | Tesseract | Battle-tested, all 6 UN languages |
| HTML pages | Playwright + BeautifulSoup | Handles JS-heavy gov sites |
| Structure parser | Custom Python (regex + heuristics) | Article/section/clause boundary detection |

### Web Discovery
| Component | Tool | Reason |
|---|---|---|
| Web crawler | Scrapy + Playwright | JS-heavy government websites |
| Local file support | file:// URL scheme | Bypasses blocked government domains |
| Source authority ranker | Custom rule-based | gov.XX TLD = Tier 1, pattern matching |
| Language detector | langdetect + fasttext | Fast, offline, 170+ languages |

### Retrieval & Knowledge
| Component | Tool | Reason |
|---|---|---|
| Vector store | ChromaDB (local) | Open-source, no external API, semantic retrieval |
| Embeddings | sentence-transformers/paraphrase-multilingual | Multilingual, runs locally |
| Pre-ranker fallback | NLI CrossEncoder (nli-distilroberta-base) | Semantic pre-filter when ChromaDB unavailable |
| Knowledge graph | NetworkX | Lightweight, tracks cross-article references |
| Span verifier | Custom NLI (entity + relation check) | HalluGraph-inspired hallucination detection |
| Keyword pre-filter | Custom Python | Skips irrelevant article+indicator pairs before LLM |

### Output
| Component | Tool | Reason |
|---|---|---|
| Structured data | JSON-LD | UN-compatible linked data format |
| Country brief | Jinja2 → Markdown → PDF | ESCAP report format |
| Audit trail | SQLite | Every decision logged, reproducible |
| Human review queue | JSON flagged list | Uncertain items for expert verification |
| Web UI | Streamlit | Demo day — judges interact via browser |

---

## RDTII Pillar 6 & 7 — Exact Indicators (RDTII 2.0 Guide)

### Pillar 6 — Cross-border Data Policies
- 6.1 Ban & local processing requirements
- 6.2 Local storage requirements
- 6.3 Infrastructure requirements
- 6.4 Conditional flow regimes
- 6.5 Not in an agreement with binding commitments on data transfer

### Pillar 7 — Domestic Data Protection & Privacy
- 7.1 Lack of comprehensive legal framework for data protection
- 7.2 Minimum period of data retention requirements
- 7.3 Data Impact Assessment or Data Protection Officer requirements
- 7.4 Requirements to allow Government access to personal data

**Scoring scale:** 0 (low compliance cost / open) → 1 (high compliance cost / restrictive)

---

## Demo Countries

| Country | Pillar 6 Key Law | Pillar 7 Key Law | PDF source | Languages |
|---|---|---|---|---|
| Thailand | PDPA + ETDA regulations | PDPA (BE 2562) | Local file (downloaded manually) | Thai + English |
| Vietnam | Cybersecurity Law Art. 26 | Decree 13/2023/ND-CP | Local file (downloaded manually) | Vietnamese + English |
| Singapore | PDPA 2012 (amended 2020) | PDPA + advisory guidelines | HTML from agc.gov.sg | English |

**Why these three:** Covers full scoring range — open (Singapore) → conditional (Thailand) → restrictive (Vietnam).

---

## Remote GPU Setup (Tailscale)

```
Your computer (runs pipeline)
      ↓
Tailscale private network
      ↓
Friend's RTX 5070 12GB (runs Ollama)
      ↓
llama3.1:8b
```

**Your .env:**
```
OLLAMA_MODEL=llama3.1:8b
OLLAMA_BASE_URL=http://FRIEND_TAILSCALE_IP:11434
```

---

## Form Question Reference (Submission Answers)

### Q1 — Linguistic conflict
- 1.1: "Shall not transfer" = absolute prohibition. "Except in accordance with requirements" = conditional permission. Default position is restriction, not openness.
- 1.2: Phrase 1 is the primary rule; Phrase 2 is its exception. Score from primary clause (restrictive). Note exception as conditional modifier.
- 1.3: LLM identifies primary clause and exception clause separately. Scores each independently. Vague exception language → UNCERTAIN. Never blends both into one score.

### Q2 — End-to-end workflow
collect → Scrapy+Playwright crawl / local file:// read
extract → Docling/Surya/BS4 → clean structured text
classify → article chunks → keyword pre-filter → NLI re-rank → Pillar 6/7 indicator matching
explain → constrained LLM with hardcoded RDTII rubric JSON
cite → verbatim quote + law name + article + URL + date + SHA256
export → JSON-LD dataset + Jinja2 country brief + SQLite audit trail + human review queue

### Q3 — Data sources
Thailand: PDPA PDF (local file), ETDA HTML — Thai + English
Vietnam: Cybersecurity Law PDF + Decree 13 PDF (local file) — Vietnamese + English
Singapore: PDPA HTML from agc.gov.sg — English

### Q4 — Anti-hallucination
"No Quote, No Score." Verbatim quote → span verifier (entity grounding + relation preservation) → citation record in SQLite. UNCERTAIN → human queue, never auto-published.

### Q5 — Authority resolution pipeline
1. Classify: HTML official = Tier 1, scanned amendment = Tier 2, guideline = Tier 3
2. Extract Tier 1 first (Docling/BS4), Tier 2 second (Surya OCR)
3. Tier 3: locate provisions only, never score
4. OCR errors: Docling → Surya → Tesseract fallback; low-confidence chunks flagged
5. Conflict: Tier 1 wins, both versions logged in SQLite audit trail

### Q6 — Hallucination reduction
LLM allowed: classify against one specific indicator, extract verbatim quote, flag ambiguity, return UNCERTAIN
LLM not allowed: score without citation, infer intent, synthesize across sources, use Tier 3
Every claim: verbatim quote → span verifier → SQLite citation record with URL + article + date + SHA256
Failure case caught: Paraphrase Trap — Tier 3 says "data must stay local," Tier 1 says "transfers require authorization." System scores Tier 1 only, logs Tier 3 as "located but not used."

---

## Repo Structure

```
rdtii-agent/
├── CLAUDE.md                        ← this file
├── CODEX_PROMPTS.md                 ← all Codex build prompts
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── Makefile
├── pyproject.toml
├── main.py                          ← CLI entry point
├── app.py                           ← Streamlit web UI (add via Prompt 9)
├── pipeline/
│   ├── discover.py                  ← Stage 1: crawler + file:// support
│   ├── extract.py                   ← Stage 2: Docling + Surya + BS4 + bundled fallback
│   ├── authority.py                 ← Stage 3: Tier ranker + conflict detector
│   ├── retrieval.py                 ← Stage 4a: ChromaDB + NLI pre-ranker + NetworkX KG
│   ├── verify.py                    ← Stage 4b: Span verifier
│   ├── reason.py                    ← Stage 5: Keyword pre-filter + Ollama + heuristic
│   └── export.py                    ← Stage 6: JSON-LD + Jinja2 + SQLite
├── rubrics/
│   ├── pillar6.json
│   └── pillar7.json
├── templates/
│   └── country_brief.md.j2
├── demo/
│   ├── thailand/output/             ← real scored outputs
│   ├── vietnam/output/
│   └── singapore/output/
├── answers/
│   ├── Q1.md through Q6.md          ← submission form answers
└── tests/
    └── test_pipeline.py             ← 9 tests (all passing)
```

---

## Key Principles (Never Break These)

> **No Quote → No Score. No Tier 1/2 Source → No Output.**

> **The LLM is a classifier, not an oracle.** Uncertainty is a first-class output.

> **The pipeline is auditable.** Every decision logged in SQLite. Every score traceable to its exact source.

> **Offline always works.** Heuristic fallback enforces all the same rules.

> **temperature=0.0 always.** Legal scoring must be deterministic.
