# RDTII Regulatory Intelligence Agent

Python 3.11+ | MIT License | RDTII 2.0 | Pillars 6 & 7

## What It Does

This tool reads legal and regulatory text for a country and scores it against Pillar 6, Cross-border Data Policies, and Pillar 7, Domestic Data Protection and Privacy, of the RDTII 2.0 framework. It produces a machine-readable JSON-LD dataset, a country brief, a SQLite audit trail, and a human review queue for items where the evidence is insufficient.

## Why It Is Trustworthy

The system follows a strict "No Quote, No Score" rule. A score is only confirmed when it has an exact verbatim quote from the source text, source title, authority tier, article or section reference, source URL, and document hash. If any of these are missing, the indicator is marked `UNCERTAIN` and routed to human review.

Sources are ranked by authority. Tier 1 sources are official legislation and gazette publications. Tier 2 sources are amendments and implementing regulations. Tier 3 sources, such as guidelines and FAQs, are used only to locate relevant provisions and are never used for scoring.

After the LLM or local classifier proposes a score, the span verifier checks that the quoted text is grounded in the source document. If the quote cannot be found, the score is rejected.

## Quick Start

### Option 1 — Ollama (free, local, recommended)

Install Ollama from https://ollama.com, then:

```bash
ollama serve                          # start local LLM server
ollama pull llama3.1:8b               # download model once

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python main.py --country thailand --pillars 6 7
```

For a remote Ollama server on a friend's machine, set the Tailscale URL:

```bash
export OLLAMA_BASE_URL=http://FRIEND_TAILSCALE_IP:11434
export OLLAMA_MODEL=llama3.1:8b
python main.py --country thailand --pillars 6 7
```

### Option 2 — Offline / no LLM (demo mode)

If Ollama is unavailable, the pipeline falls back to the bundled heuristic classifier. All anti-hallucination rules still apply.

```bash
python main.py --country thailand --pillars 6 7
```

### Browser UI

```bash
streamlit run app.py
```

The UI calls the same backend pipeline used by the CLI and reads the generated JSON-LD, country brief, and review queue files.

## Output Example

Sample JSON-LD score entry for Thailand PDPA Section 28:

```json
{
  "@type": "rdtii:IndicatorScore",
  "rdtii:pillar": 6,
  "rdtii:indicatorId": "6.4",
  "rdtii:indicatorName": "Conditional flow regimes",
  "score": 0.5,
  "confidence": "MEDIUM",
  "verbatim_quote": "shall have adequate data protection standard",
  "source_url": "https://www.oag.go.th/wp-content/uploads/2021/11/Personal-Data-Protection-Act-BE-2562-2019.pdf",
  "rdtii:sourceTitle": "Personal Data Protection Act B.E. 2562 (2019)",
  "rdtii:sourceTier": 1,
  "article_ref": "Section 28",
  "rdtii:sha256": "87c3d6c659a7099769e5c128a7fe41fc936a8ad36c8ea539802d22316f2d2e4c",
  "human_review_required": false
}
```

## Architecture

```text
Country + Pillar Scope
  -> Discovery: seed sources, crawl government sites, assign authority tier
  -> Extraction: Docling for PDFs, Surya/Tesseract for OCR, BeautifulSoup for HTML
  -> Authority Resolution: score Tier 1 and Tier 2 only, flag conflicts
  -> Hybrid RAG + Knowledge Graph: retrieve article-level legal chunks and cross-references
  -> Legal Reasoning Chain: classify against hardcoded RDTII rubrics with required quotes
  -> Verified Output: JSON-LD, country brief, SQLite audit trail, human review queue
```

## Demo Countries

The current demo scope covers Thailand, Vietnam, and Singapore.

Thailand uses the Personal Data Protection Act B.E. 2562 and related government sources. Vietnam uses the Cybersecurity Law, Article 26, and Decree 13/2023/ND-CP on Personal Data Protection. Singapore uses the Personal Data Protection Act 2012 and PDPC sources.

These countries show a useful range of regulatory approaches: Singapore is comparatively open, Thailand is conditional, and Vietnam includes stronger localization obligations.

## Extending To A New Country

1. Add official Tier 1 or Tier 2 source URLs for the country in `pipeline/discover.py`.
2. Add any country-specific exact-phrase demo rules or bundled offline excerpts only when needed for a reproducible demo.

The general pipeline does not require new scoring logic for every country. New legal texts are matched against the existing RDTII Pillar 6 and 7 rubrics.

## LLM Backends

Ollama is the only supported LLM backend. It runs locally or on a private Tailscale address and uses `OLLAMA_MODEL=llama3.1:8b` unless configured otherwise.

When Ollama is unavailable, the system falls back to the local heuristic classifier. The fallback still enforces No Quote, No Score and never invents citations.

## License

MIT License.
