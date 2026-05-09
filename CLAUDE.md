# CLAUDE.md — RDTII Regulatory Intelligence Agent
## Hackathon: Global Hackathon on Using AI for Digital Trade Regulatory Analysis
## Submission Deadline: 15 May 2026 | Event: Paperless Trade Week, Bangkok, June 2026

---

## Project Vision

> Build an AI pipeline that replicates — and eventually surpasses — the work of a $2,000/country human regulatory researcher, starting with Pillar 6 (Cross-border Data Policies) and Pillar 7 (Domestic Data Policies) of the RDTII 2.0 framework.

**Our differentiator:** Not just a RAG pipeline. A **Legal Reasoning Chain** backed by a Hybrid RAG + Knowledge Graph architecture that produces auditable, conflict-resolved, span-verified, human-reviewable regulatory evidence — the way a lawyer argues a case, not the way a chatbot answers a question.

---

## Current Status

Ollama is the primary LLM backend (`LLM_BACKEND=ollama`) with `qwen2.5:3b` as the default local model for 4GB VRAM machines. OpenAI and Anthropic remain supported as optional cloud backends, and the local heuristic classifier remains the automatic fallback whenever the selected LLM backend is unavailable.

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
│  - NetworkX KG      → cross-ref tracking     │
│    ("as defined in Section X" links)         │
│  - Span verifier    → claim ↔ source match   │
│    (HalluGraph-style: Entity Grounding +     │
│     Relation Preservation check)             │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│  STAGE 5: LEGAL REASONING CHAIN  ★           │
│  - RDTII rubric loader (Pillar 6+7 JSON)     │
│  - Constrained LLM (Ollama local primary)    │
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
- Identify linguistic ambiguity between provisions (e.g. absolute prohibition vs conditional exception)
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

**Rule:** Tier 1 vs Tier 2 conflict → score from Tier 1, flag conflict for human review.
**Rule:** Tier 3 sources are used ONLY to locate relevant provisions in Tier 1/2, never to score.
**Rule:** If no Tier 1 or Tier 2 source found → indicator scored as UNCERTAIN, human review required.

---

## Anti-Hallucination Design

### The "No Quote, No Score" Rule
Every RDTII indicator score must be accompanied by ALL of:
- Exact verbatim quoted text (not paraphrased)
- Source name + authority tier
- Article / Section / Page reference
- URL or document SHA256 hash (for reproducibility)
- Date of the source document

If any of these are missing → score is rejected, item added to human review queue, never published.

### Span-Level Verification (HalluGraph-inspired)
After LLM produces a classification + quote:
1. Extract entities from the quote (law names, article numbers, dates, obligations)
2. Check each entity exists verbatim in the source document (Entity Grounding check)
3. Check the relationship asserted is supported by the source (Relation Preservation check)
4. If either check fails → flag as UNCERTAIN, route to human queue

### Failure Cases We Catch

**The Paraphrase Trap:** A ministry guideline (Tier 3) says "data must be kept within the country."
Official law (Tier 1) says "data transfers abroad require authorization." A naive LLM might merge
both into one localization score. Our system:
1. Identifies both sources and assigns tiers
2. Scores from Tier 1 only
3. Flags Tier 3 paraphrase in audit trail as "located but not used for scoring"
4. Outputs only the Tier 1 citation with verbatim quote

**The Linguistic Conflict Trap:** A law says "shall not transfer" (absolute prohibition) followed
by "except in accordance with requirements" (conditional permission). Our system:
1. Identifies the primary clause (prohibition) and the exception clause separately
2. Scores the primary clause as the default regulatory position
3. Scores the exception clause as a modifier with its own conditions
4. If exception conditions are vague → flags UNCERTAIN on the modifier, not the whole indicator

---

## Full Tech Stack

### Core
| Component | Tool | Reason |
|---|---|---|
| Language | Python 3.11+ | Ecosystem depth, UN-friendly |
| Orchestration | Custom pipeline | No LangChain — too opaque for UN auditors |
| LLM (primary) | Ollama — local, free, no API key (`LLM_BACKEND=ollama`); default model: `qwen2.5:3b`; also supports `llama3.2:3b`, `qwen2.5:7b`, `mistral:7b` | No quota limits, fully local execution, deterministic legal scoring on 4GB VRAM |
| LLM (cloud A) | OpenAI `gpt-4o` (`LLM_BACKEND=openai`, `OPENAI_API_KEY`) | Optional cloud backend |
| LLM (cloud B) | Anthropic Claude Sonnet 4 (`LLM_BACKEND=anthropic`, `ANTHROPIC_API_KEY`) | Optional cloud backend |
| LLM (offline) | Local heuristic classifier (automatic fallback, no config) | Fully air-gapped mode option |
| License | MIT open-source | Required by hackathon |

### Document Extraction
| Component | Tool | Reason |
|---|---|---|
| Digital PDF | Docling (IBM Research) | 97.9% table accuracy, preserves legal structure, local execution |
| Scanned PDF (primary) | Surya OCR | 90+ languages, open-source, multilingual layout analysis |
| Scanned PDF (fallback) | Tesseract | Battle-tested, all 6 UN languages |
| HTML pages | Playwright + BeautifulSoup | Handles JS-heavy gov sites |
| Structure parser | Custom Python (regex + heuristics) | Article/section/clause boundary detection |

### Web Discovery
| Component | Tool | Reason |
|---|---|---|
| Web crawler | Scrapy + Playwright | JS-heavy government websites |
| Source authority ranker | Custom rule-based | gov.XX TLD = Tier 1, pattern matching |
| Language detector | langdetect + fasttext | Fast, offline, 170+ languages |

### Retrieval & Knowledge
| Component | Tool | Reason |
|---|---|---|
| Vector store | ChromaDB (local) | Open-source, no external API, semantic retrieval |
| Embeddings | sentence-transformers/paraphrase-multilingual | Multilingual, runs locally |
| Knowledge graph | NetworkX | Lightweight, tracks cross-article references |
| Span verifier | Custom NLI (entity + relation check) | HalluGraph-inspired hallucination detection |

### Multilingual Support
| Component | Tool | Reason |
|---|---|---|
| Translation | Helsinki-NLP/opus-mt | Open-source, runs locally, no API cost |
| Target languages | Thai, Vietnamese, Russian, Chinese, English | Asia-Pacific focus |
| OCR multilingual | Surya OCR | Arabic, Chinese, Russian, Thai, 90+ total |

### Output
| Component | Tool | Reason |
|---|---|---|
| Structured data | JSON-LD | UN-compatible linked data format |
| Country brief | Jinja2 → Markdown → PDF | ESCAP report format |
| Audit trail | SQLite | Every decision logged, reproducible |
| Human review queue | JSON flagged list | Uncertain items for expert verification |

---

## RDTII Pillar 6 & 7 — Exact Indicators (from RDTII 2.0 Guide)

### Pillar 6 — Cross-border Data Policies
- Ban & local processing requirements
- Local storage requirements
- Infrastructure requirements
- Conditional flow regimes
- Not in an agreement with binding commitments on data transfer

### Pillar 7 — Domestic Data Protection & Privacy
- Lack of comprehensive legal framework for data protection
- Minimum period of data retention requirements
- Data Impact Assessment or Data Protection Officer requirements
- Requirements to allow Government access to personal data

**Scoring scale:** 0 (low compliance cost / open) → 1 (high compliance cost / restrictive)
**Score > 0 triggers when:** differential treatment of foreign providers, additional compliance
costs for online services, or absence of key international norms.

---

## Demo Countries (Submission)

| Country | Pillar 6 Key Law | Pillar 7 Key Law | Doc Types | Languages |
|---|---|---|---|---|
| Thailand | PDPA + ETDA regulations | PDPA (BE 2562) | Digital PDF + HTML | Thai + English |
| Vietnam | Cybersecurity Law Art. 26 | Decree 13/2023/ND-CP | Digital PDF | Vietnamese + English |
| Singapore | PDPA 2012 (amended 2020) | PDPA + advisory guidelines | HTML + PDF | English |

**Why these three:** Known regulatory complexity across Pillar 6 + 7, laws available in multiple
formats and languages, covers a spectrum from open (Singapore) to conditional (Thailand) to
restrictive (Vietnam) — a good stress test of the full scoring range.

---

## Submission Plan (Before 15 May 2026)

### Now → 9 May: Foundation
- [ ] Read RDTII 2.0 guide — Chapter 3, Pillar 6 (p.41) and Pillar 7 (p.49)
- [ ] Manually score Thailand PDPA on all Pillar 6 + 7 indicators (ground truth)
- [ ] Set up GitHub repo (MIT license, open-source)
- [ ] Write Q1 answers (linguistic conflict — legal analysis first)
- [ ] Set up Python project structure (see repo layout below)

### 9 May → 12 May: Build Core Pipeline
- [ ] Stage 1: Scrapy crawler for gov.th + OAG Thailand PDPA page
- [ ] Stage 2: Docling extractor for Thailand PDPA PDF
- [ ] Stage 2: Surya OCR test on a scanned Thai legal doc
- [ ] Stage 3: Source authority ranker (Tier 1/2/3 classifier)
- [ ] Stage 4: ChromaDB setup + NetworkX KG for cross-references
- [ ] Stage 4: Span verifier (entity grounding check)
- [ ] Stage 5: RDTII rubric JSON (Pillar 6 + 7 hardcoded)
- [ ] Stage 5: Constrained LLM prompting chain
- [ ] Stage 6: JSON-LD output + Jinja2 country brief template
- [ ] Write Q2, Q3, Q4, Q5, Q6 answers

### 12 May → 15 May: Polish + Submit
- [ ] End-to-end demo run: Thailand → Pillar 6 + 7 full output
- [ ] Add Vietnam as second demo country
- [ ] Record 5-minute concept video (see script below)
- [ ] Write Technical Memo (750 words max)
- [ ] Final review + submit all form answers

---

## Concept Video Script (5 minutes)

```
0:00–0:45  The problem
           ESCAP pays $2,000/country to manually read laws.
           100+ countries. 12 pillars. Slow, expensive, gets stale.

0:45–2:00  Our pipeline (show the architecture diagram)
           Discovery → Extraction → Authority Resolution →
           Hybrid RAG + KG → Legal Reasoning Chain → Verified Output

2:00–3:30  Live demo
           Input: "Thailand, Pillar 6 + 7"
           Watch: crawler finds PDPA → Docling extracts →
           Tier ranker assigns authority → KG links cross-refs →
           Constrained LLM scores "Ban & local processing = 0.5" →
           Citation: "PDPA Section 28, 2019, oag.go.th/..."

3:30–4:15  Show the output
           JSON-LD dataset with per-indicator scores + citations
           Country brief in ESCAP format

4:15–5:00  Why it's trustworthy
           No quote = no score (show a blocked uncertain item)
           Human review queue (show flagged items)
           Fully open-source, runs locally, MIT license
```

---

## Form Question Reference

### Q1 — Linguistic conflict answer approach
- 1.1: "Shall not transfer" = absolute prohibition. "Except in accordance with requirements" =
  conditional permission. Conflict: is the default position restriction or openness? The two
  phrases use contradictory framings in the same provision.
- 1.2: Phrase 1 is the primary rule; Phrase 2 is its exception. In legal drafting, the exception
  modifies but does not negate the default. Score from the primary clause (restrictive), note
  the exception as a modifier with conditions.
- 1.3: Force the LLM to identify primary clause and exception clause separately. Score the
  primary clause first. Score the exception conditions separately. Flag vague exception language
  as UNCERTAIN. Never allow the LLM to blend both phrases into a single score.

### Q2 — End-to-end workflow
collect → Scrapy+Playwright crawl gov sites, rank by Tier
extract → Docling/Surya/BS4 → clean structured text
classify → article-level chunking → matched to Pillar 6/7 indicator
explain → constrained LLM with hardcoded RDTII rubric JSON
cite → verbatim quote + law name + article + URL + date
export → JSON-LD dataset + Jinja2 country brief + SQLite audit trail

### Q3 — Data sources
Thailand (demo): PDPA PDF (digital) from oag.go.th, ETDA HTML pages, Thai + English
Vietnam (demo): Cybersecurity Law PDF, Decree 13 PDF, Vietnamese + English
Singapore (demo): PDPA HTML from agc.gov.sg, English only

### Q4 — Anti-hallucination / citation method
"No Quote, No Score" rule. Every claim must have verbatim text, source name+tier,
article/section, URL/hash, date. Span verifier checks entity grounding and relation
preservation. Uncertain items go to human queue, never auto-published.

### Q5 — Authority resolution pipeline
1. Classify source: HTML official page = Tier 1, scanned PDF amendment = Tier 2,
   ministry guideline = Tier 3
2. Extract relevant clause from Tier 1 first
3. Use Tier 2 for amendments/updates, flag version conflicts
4. Use Tier 3 only to locate provisions in Tier 1/2, never score from it
5. OCR errors: Docling fallback to Surya, then Tesseract; flag low-confidence OCR
   chunks for human review
6. Conflicts: Tier 1 always wins; conflict logged in audit trail with both versions

### Q6 — Hallucination reduction design
LLM allowed: classify provision against specific indicator, extract verbatim quote,
flag ambiguity, return UNCERTAIN
LLM not allowed: score without citation, infer intent, synthesize across sources,
use Tier 3 for scoring
Every claim linked to evidence: verbatim quote → span verifier → citation record in SQLite
Failure case caught: Paraphrase Trap — Tier 3 guideline says "data must stay local,"
Tier 1 law says "transfers require authorization." System assigns tiers, scores only from
Tier 1, flags Tier 3 as located-but-unused, outputs only Tier 1 citation.

---

## Repo Structure

```
rdtii-agent/
├── CLAUDE.md                        ← this file
├── README.md
├── requirements.txt
├── pipeline/
│   ├── discover.py                  ← Stage 1: Scrapy + Playwright crawler
│   ├── extract.py                   ← Stage 2: Docling + Surya + BS4
│   ├── authority.py                 ← Stage 3: Tier ranker + conflict detector
│   ├── retrieval.py                 ← Stage 4: ChromaDB + NetworkX KG
│   ├── verify.py                    ← Stage 4: Span verifier (entity + relation)
│   ├── reason.py                    ← Stage 5: Constrained LLM reasoning chain
│   └── export.py                    ← Stage 6: JSON-LD + Jinja2 + SQLite
├── rubrics/
│   ├── pillar6.json                 ← RDTII Pillar 6 indicators (exact from guide)
│   └── pillar7.json                 ← RDTII Pillar 7 indicators (exact from guide)
├── templates/
│   └── country_brief.md.j2          ← Jinja2 country brief template (ESCAP format)
├── demo/
│   ├── thailand/
│   │   ├── sources.json             ← discovered source URLs + tiers
│   │   ├── extracted/               ← cleaned legal text per article
│   │   └── output/                  ← scored JSON-LD + country brief PDF
│   ├── vietnam/
│   └── singapore/
├── answers/
│   ├── Q1.md
│   ├── Q2.md
│   ├── Q3.md
│   ├── Q4.md
│   ├── Q5.md
│   └── Q6.md
└── outputs/
    ├── thailand_pillar6_dataset.json
    ├── thailand_pillar7_dataset.json
    ├── thailand_country_brief.pdf
    └── audit/
        └── thailand_run_001.sqlite
```

---

## Key Principles

> **The system doesn't trust itself.** Every output is a claim that must be proven by a verbatim
> citation from an authoritative source. The LLM is a classifier, not an oracle. Uncertainty is
> a first-class output, not a failure. Humans are always in the loop for uncertain items.

> **No Quote → No Score. No Tier 1/2 Source → No Output.**

> **The pipeline is auditable.** Every decision — what was found, what tier it was assigned,
> what the LLM classified, what the span verifier checked, what was flagged — is logged in
> SQLite per run. A UN researcher can trace any score back to its exact source.

This is what makes it trustworthy enough for the UN to publish.
