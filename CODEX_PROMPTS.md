# CODEX PROMPTS — RDTII Agent Build Plan
## Read CLAUDE.md and WORKFLOW.md first before executing any prompt below.
## Execute prompts IN ORDER. Each builds on the previous.
## Deadline: 15 May 2026

---

## HOW TO USE THIS FILE

Each prompt below is a self-contained task for Codex CLI.
Copy the block between the triple backticks and paste it to Codex.
Wait for it to finish and verify before moving to the next.

---

## CURRENT STATUS (as of 13 May 2026)

✅ Pipeline runs end-to-end for Thailand, Vietnam, Singapore
✅ Ollama backend working — llama3.1:8b on friend's RTX 5070 via Tailscale
✅ LLM scoring confirmed — [LLM:ollama] logs verified, HTTP 200 OK
✅ 18 pytest tests passing
✅ 3-tier authority system, conflict detection, span verifier
✅ JSON-LD + SQLite audit + country brief + human review queue
✅ .env configured with OLLAMA_BASE_URL pointing to remote GPU
✅ Thailand PDFs downloaded to /pdf/thailand/

❌ Real PDF not being read — docling/surya/pytesseract not installed
   Pipeline falls back to bundled_demo_text (6 sections) instead of real PDF (178 sections)
   ROOT CAUSE: PyMuPDF (fitz) IS already in requirements but never tried before OCR stack
❌ Keyword pre-filter not added — LLM called ~150 times per run (slow)
❌ NLI CrossEncoder pre-ranker not added — keyword fallback only for retrieval
❌ Streamlit UI not wired to rdtii-agent backend (only prototype exists in un-hackathon)
❌ Indonesia not added as 4th demo country
❌ file:// URL handler not yet in extract.py

## CONFIRMED SCORES SO FAR (bundled text + llama3.1:8b)
- 4 confirmed scores out of 9 indicators
- 5 in human review queue (UNCERTAIN)
- All confirmed scores: extraction_method = bundled_demo_text
- Target with real PDF: 8-9 confirmed scores out of 9

---

## ARCHITECTURE CONTEXT

Two repos exist:
  un-hackathon/  → Streamlit UI prototype (NLI CrossEncoder, Thailand/Vietnam/Indonesia)
  rdtii-agent/   → Full backend pipeline (this is the source of truth)

Strategy: keep rdtii-agent as backend, wire un-hackathon Streamlit as thin UI layer.
The Streamlit app must call run_pipeline() from rdtii-agent, not duplicate scoring logic.

LLM stack:
  Primary:  Ollama llama3.1:8b on friend's RTX 5070 via Tailscale
  Fallback: Local heuristic classifier (deterministic, all rules apply)
  No OpenAI, No Anthropic (no paid APIs)

Rule that must never break: No Quote → No Score. No Tier 1/2 Source → No Output.

---

## PROMPT 9 — Fix real PDF ingestion using PyMuPDF

Priority: CRITICAL — this is the single biggest quality jump available
Impact: Confirmed scores go from 4/9 → 8-9/9, extraction_method changes from
        bundled_demo_text to pymupdf

Context: Docling, Surya, and Tesseract are not installed. BUT pymupdf (fitz)
IS already in requirements.txt and IS installed. The extractor never tries it
because the fallback chain goes Docling → Surya → Tesseract → bundled text,
skipping PyMuPDF entirely.

```
Read CLAUDE.md and WORKFLOW.md.

The pipeline extracts PDFs using Docling → Surya → Tesseract → bundled text.
But Docling, Surya, and Tesseract are NOT installed. PyMuPDF (fitz) IS installed.
The pipeline never tries PyMuPDF because it is not in the fallback chain.

TASK 1 — Insert PyMuPDF as the first PDF extraction method in pipeline/extract.py

In _extract_pdf(), make PyMuPDF the FIRST thing tried, before Docling:

  def _extract_pdf(url: str) -> tuple[str, str]:
      fallback = _demo_fallback_text(url)

      # Download PDF to temp file first
      try:
          import urllib.request, tempfile, os
          with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
              urllib.request.urlretrieve(url, tmp.name)
              tmp_path = tmp.name
      except Exception as e:
          if fallback:
              return fallback, "bundled_demo_text"
          return "", "failed"

      # Try PyMuPDF first (installed, fast, good for digital PDFs)
      try:
          import fitz   # PyMuPDF
          doc = fitz.open(tmp_path)
          pages = []
          for page in doc:
              pages.append(page.get_text())
          doc.close()
          text = "\n".join(pages)
          if text and len(text.strip()) > 200:
              os.unlink(tmp_path)
              return text, "pymupdf"
      except Exception as e:
          logger.warning(f"[extract] PyMuPDF failed: {e} — trying Docling")

      # Then try Docling (if installed)
      # Then Surya OCR (if installed)
      # Then Tesseract (if installed)
      # Keep all existing fallbacks after PyMuPDF

TASK 2 — Add file:// URL handler in _extract_pdf()

When a URL starts with "file://", read directly from disk instead of downloading:

  def _extract_pdf(url: str) -> tuple[str, str]:
      # Handle local file:// URLs
      if url.startswith("file://"):
          local_path = url.replace("file://", "")
          try:
              import fitz
              doc = fitz.open(local_path)
              pages = [page.get_text() for page in doc]
              doc.close()
              text = "\n".join(pages)
              if text and len(text.strip()) > 200:
                  return text, "pymupdf_local"
          except Exception as e:
              logger.error(f"[extract] Local PDF read failed for {local_path}: {e}")
          return "", "failed"
      # ... rest of download+extract logic

TASK 3 — Add Thailand local PDF to discover.py seed sources

The Thailand PDFs are at:
  /home/engineerkim/Desktop/rdtii-agent/pdf/thailand/

List what files are there with os.listdir(), then add the most relevant one
as a seed source with file:// URL:

  {
    "url": "file:///home/engineerkim/Desktop/rdtii-agent/pdf/thailand/FILENAME.pdf",
    "title": "Personal Data Protection Act B.E. 2562 (2019) — local copy",
    "language": "en",
    "doc_type": "pdf",
    "pillar_hint": [6, 7],
  }

Add this as the FIRST Thailand seed source (highest priority — local file
does not fail due to DNS or 403 errors).

TASK 4 — Add extraction_method flag to output

In pipeline/export.py, when building the JSON-LD indicator entry, add:
  "rdtii:extractionMethod": s.extraction_method if hasattr(s, 'extraction_method') else "unknown"

This lets ESCAP researchers know whether a score came from a real PDF or
bundled demo text — required for publication trust.

TASK 5 — Verify

Run:
  python main.py --country thailand --pillars 6 7

Assert:
  - At least one indicator shows extraction_method = "pymupdf" or "pymupdf_local"
  - Article chunks count is significantly higher than 8 (should be 40+)
  - At least 6 confirmed scores (up from 4)
  - Log shows real section numbers being parsed (Section 77, Section 14, etc.)

Run:
  pytest tests/ -v
Assert: all tests still pass.
```

---

## PROMPT 10 — Add keyword pre-filter and NLI CrossEncoder pre-ranker

Priority: HIGH — cuts LLM calls from ~150 to ~15, makes full run under 2 minutes

```
Read CLAUDE.md and WORKFLOW.md.

The pipeline currently calls Ollama for every article × every indicator pair.
With 17+ articles and 9 indicators that is ~150+ LLM calls per country run.
With real PDFs (40+ articles) it will be 360+ calls — too slow for a demo.

TASK 1 — Add keyword pre-filter in pipeline/reason.py

Before calling _call_llm(), check if the article contains any indicator keywords.
If not, skip the LLM call entirely and return UNCERTAIN immediately.

Add this function to reason.py:

  def _is_relevant(article_text: str, indicator: dict) -> bool:
      """
      Fast keyword check before LLM call.
      If no indicator keywords appear in the article text, skip LLM entirely.
      Returns True if article might be relevant, False to skip.
      """
      text_lower = article_text.lower()
      keywords = indicator.get("keywords", [])
      if not keywords:
          return True  # no keywords defined — always send to LLM
      return any(kw.lower() in text_lower for kw in keywords)

In score_indicator(), before building the prompt and calling _call_llm():

  if not _is_relevant(article_text, indicator):
      logger.debug(
          f"[reason] Skipping {indicator['id']} on '{article_ref}' — no keyword match"
      )
      return _uncertain(
          indicator, source_meta, article_ref,
          "Article skipped — no relevant keywords found (pre-filter)."
      )

TASK 2 — Add NLI CrossEncoder as retrieval pre-ranker in pipeline/retrieval.py

When ChromaDB is unavailable, use NLI CrossEncoder to rank articles by
relevance to the indicator before returning top-K. This is smarter than
keyword overlap scoring.

Add this to retrieval.py:

  def _nli_rerank(articles: list[dict], indicator: dict, top_k: int) -> list[dict]:
      """
      Re-rank articles using NLI CrossEncoder when ChromaDB is unavailable.
      Uses cross-encoder/nli-distilroberta-base — small, fast, no GPU needed.
      """
      query = f"{indicator['name']}. {indicator['description']}"
      try:
          from sentence_transformers import CrossEncoder
          model = CrossEncoder("cross-encoder/nli-distilroberta-base")
          pairs = [(query, a.get("text", "")[:512]) for a in articles]
          scores = model.predict(pairs)
          ranked = sorted(zip(scores, articles), key=lambda x: x[0], reverse=True)
          return [a for _, a in ranked[:top_k]]
      except Exception as e:
          logger.warning(f"[retrieval] NLI reranker failed ({e}) — keyword fallback")
          return _keyword_fallback(query, top_k)

Replace _keyword_fallback call in _semantic_search() with _nli_rerank() when
ChromaDB is unavailable.

TASK 3 — Add num_ctx optimization to Ollama calls in reason.py

In _call_ollama(), add num_ctx to reduce VRAM usage and speed up inference:

  response = client.chat.completions.create(
      model=model,
      max_tokens=512,
      messages=[{"role": "user", "content": prompt}],
      temperature=0.0,
      extra_body={"num_ctx": 2048},
  )

2048 context is enough for our prompts (under 800 tokens each).
This frees ~2GB VRAM and speeds up each call on the remote RTX 5070.

TASK 4 — Verify speed improvement

Run:
  time python main.py --country thailand --pillars 6 7

Assert:
  - Run completes in under 3 minutes (was hanging before)
  - Log shows "Skipping ... no keyword match" for irrelevant pairs
  - LLM call count (count of [LLM:ollama] lines in log) is under 30
  - Confirmed scores are same or better than before this prompt
  - pytest tests/ -v still passes
```

---

## PROMPT 11 — Wire Streamlit UI to rdtii-agent backend

Priority: HIGH — judges need a UI, not a terminal

Context: un-hackathon/ has a Streamlit app that runs its own NLI scoring.
We need a NEW app.py in rdtii-agent/ that calls run_pipeline() from main.py
and shows the results. The un-hackathon Streamlit logic must NOT be copied —
it uses a different scoring model.

```
Read CLAUDE.md and WORKFLOW.md.

Create app.py in the rdtii-agent/ root directory.
This is a NEW Streamlit UI that wraps the existing pipeline backend.
Do NOT copy any scoring logic from un-hackathon/un-rdtii/app.py.
Do NOT duplicate mapper.py, crawler.py, or extractor.py logic.
The UI calls run_pipeline() from main.py and displays what it returns.

The app must have these sections:

SIDEBAR:
  - Title: "RDTII Regulatory Intelligence Agent"
  - Country selector: selectbox with Thailand, Vietnam, Singapore
  - Pillar checkboxes: Pillar 6 (checked by default), Pillar 7 (checked by default)
  - "Run Analysis" button
  - Ollama status indicator: show green/red dot based on curl to OLLAMA_BASE_URL/api/tags
  - Small note: "Powered by llama3.1:8b via Ollama"

MAIN AREA — before run:
  - Brief explanation of what the tool does (2 sentences max)
  - Show the RDTII framework: Pillar 6 and 7 indicator names in a table

MAIN AREA — after run:
  Tab 1: "Scores"
    - Summary metrics row: total indicators, confirmed, uncertain, pillars covered
    - Score table with columns: ID, Indicator, Score, Confidence, Article, Tier, Review?
    - Color code: green for confirmed, yellow for UNCERTAIN
    - Each confirmed row is expandable: shows verbatim quote + source URL + rationale

  Tab 2: "Country Brief"
    - Display the generated Markdown country brief inline
    - "Download Brief" button for the .md file

  Tab 3: "Evidence (JSON-LD)"
    - Show the raw JSON-LD dataset in a code block
    - "Download JSON-LD" button

  Tab 4: "Human Review Queue"
    - Table of UNCERTAIN items: indicator, reason, article checked, source
    - "Download Review Queue" button

IMPORTANT implementation notes:
  - Import run_pipeline from main.py
  - Call it with: scores = run_pipeline(country, pillars)
  - run_pipeline() already returns all_scores list
  - Use st.spinner() while pipeline runs
  - Use st.cache_data with a short TTL to avoid re-running on every interaction
  - Handle the case where Ollama is not reachable gracefully — show a warning
    but still allow offline heuristic run
  - Keep the UI simple — Streamlit default theme, no custom CSS needed

After creating app.py:
  streamlit run app.py

Assert:
  - App loads without error
  - Run Analysis button triggers the pipeline
  - Score table appears with correct columns
  - At least one expandable row shows a verbatim quote
  - Download buttons work
```

---

## PROMPT 12 — Add Indonesia as 4th demo country

Priority: MEDIUM — matches friend's repo, larger ASEAN economy

```
Read CLAUDE.md and WORKFLOW.md.

Add Indonesia as a 4th demo country. Indonesia has sector-specific data
localization rules that score differently from Thailand/Vietnam/Singapore,
providing useful range for the demo.

TASK 1 — Add Indonesia seed sources to pipeline/discover.py

Key Indonesian laws for Pillar 6 and 7:
  - Government Regulation PP 71/2019 on Electronic Systems and Transactions
  - Personal Data Protection Law (UU PDP) 2022

Add seed sources:
  {
    "url": "https://jdih.kominfo.go.id/produk_hukum/view/id/555",
    "title": "Government Regulation PP 71/2019 on Electronic Systems",
    "language": "id",
    "doc_type": "html",
    "pillar_hint": [6, 7],
  },
  {
    "url": "https://peraturan.go.id/id/uu-nomor-27-tahun-2022",
    "title": "Personal Data Protection Law (UU PDP) 2022",
    "language": "id",
    "doc_type": "html",
    "pillar_hint": [7],
  }

Add vanity URL tier rules: jdih.kominfo.go.id and peraturan.go.id = Tier 1

TASK 2 — Add Indonesia bundled demo text to pipeline/extract.py

Add Indonesia to _demo_fallback_for_country():

  if country_key == "indonesia":
      return """
  Government Regulation PP 71/2019 on Electronic Systems and Transactions

  Article 21. Electronic System Providers that have strategic Electronic
  Systems must place their Data Center and Disaster Recovery Center in
  Indonesian territory.

  Article 22. Electronic System Providers that operate Public Electronic
  Systems shall store, process, and/or present Electronic Systems and
  Electronic Data within Indonesian territory.

  Personal Data Protection Law (UU PDP) No. 27 of 2022

  Article 3. Personal Data includes specific Personal Data and general
  Personal Data.

  Article 65. The transfer of Personal Data to other countries may be
  carried out if the receiving country has an equivalent level of Personal
  Data protection to this Law, or if the Personal Data Subject has given
  explicit consent.

  Article 67. Personal Data Controllers and Personal Data Processors are
  prohibited from transferring Personal Data to countries that do not have
  equivalent Personal Data protection standards unless an exception applies.
  """

Also add URL matching: if "jdih.kominfo" or "peraturan.go.id" in url_lower.

TASK 3 — Add Indonesia heuristic scoring rules to pipeline/reason.py

  "6.2": rules already exist — add:
      (1.0, "must place their Data Center and Disaster Recovery Center in Indonesian territory"),
      (1.0, "shall store, process, and/or present Electronic Systems and Electronic Data within Indonesian territory"),
  "6.4": add:
      (0.5, "receiving country has an equivalent level of Personal Data protection"),
      (0.5, "Personal Data Subject has given explicit consent"),
  "7.1": add:
      (0.0, "Personal Data Protection Law (UU PDP) No. 27 of 2022"),
  "6.1": add:
      (1.0, "prohibited from transferring Personal Data to countries that do not have equivalent Personal Data protection standards"),

TASK 4 — Update Makefile

  run-indonesia:
          python main.py --country indonesia --pillars 6 7

  run-all:  (add indonesia to existing run-all)

TASK 5 — Verify

  python main.py --country indonesia --pillars 6 7

Assert:
  - Pipeline completes
  - At least 2 confirmed scores (6.2 = 1.0 for data localization requirement)
  - Indonesia country brief written to outputs/
  - pytest tests/ -v passes
```

---

## PROMPT 13 — Final submission check

Priority: CRITICAL — run this on 14 May, day before deadline

```
Read CLAUDE.md and WORKFLOW.md. This is the final pre-submission check.
Run every item and fix what fails. Report ✅ or ❌ for each.

1. PIPELINE CHECK — run all 4 countries:
   python main.py --country thailand --pillars 6 7
   python main.py --country vietnam --pillars 6 7
   python main.py --country singapore --pillars 6 7
   python main.py --country indonesia --pillars 6 7
   Assert: each run completes and writes 4 output files
   Assert: at least one confirmed score per country shows [LLM:ollama] in logs
   Assert: Thailand has at least 6 confirmed scores (not just 4)

2. REAL PDF CHECK:
   Check outputs/thailand_rdtii_dataset.jsonld
   Assert: at least one score has extractionMethod = "pymupdf" or "pymupdf_local"
   If all scores still show bundled_demo_text → FAIL → re-run Prompt 9

3. STREAMLIT UI CHECK:
   streamlit run app.py
   Assert: app loads, Run Analysis works for Thailand
   Assert: score table shows confirmed scores with expandable quotes
   Assert: Download JSON-LD button works

4. TEST CHECK:
   pytest tests/ -v
   Assert: all tests pass (expect 18+)

5. SPEED CHECK:
   time python main.py --country thailand --pillars 6 7
   Assert: completes in under 3 minutes

6. JSON-LD VALIDITY CHECK:
   python -m json.tool outputs/thailand_rdtii_dataset.jsonld > /dev/null
   python -m json.tool outputs/vietnam_rdtii_dataset.jsonld > /dev/null
   python -m json.tool outputs/singapore_rdtii_dataset.jsonld > /dev/null
   python -m json.tool outputs/indonesia_rdtii_dataset.jsonld > /dev/null
   Assert: all valid JSON

7. AUDIT TRAIL CHECK:
   sqlite3 outputs/rdtii_audit.db \
     "select distinct stage from audit_log order by stage;"
   Assert: all 6 stages present: authority, discover, export, extract, reason, retrieval

8. ANSWER FILES CHECK:
   for i in 1 2 3 4 5 6; do wc -w answers/Q${i}.md; done
   Assert: no file is 0 words

9. DEMO FILES CHECK:
   Assert demo/thailand/output/ has 3 files
   Assert demo/vietnam/output/ has 3 files
   Assert demo/singapore/output/ has 3 files

10. CLEAN RUN CHECK:
    rm -rf outputs/
    python main.py --country thailand --pillars 6 7
    Assert: outputs/ recreated with all 4 files

Report ✅ or ❌ for each of the 10 checks.
If all ✅ → print "READY TO SUBMIT"
If any ❌ → print exactly what failed and fix it before finishing.
```

---

## EXECUTION ORDER SUMMARY

| # | Prompt | Priority | Est. Time | Deadline |
|---|--------|----------|-----------|----------|
| 1–8 | Previous prompts | ✅ Done | — | Done |
| **9** | **Real PDF via PyMuPDF + file:// handler** | **CRITICAL** | **45 min** | **Today** |
| **10** | **Keyword pre-filter + NLI reranker + num_ctx** | **HIGH** | **30 min** | **Today** |
| **11** | **Streamlit UI wired to rdtii-agent backend** | **HIGH** | **1 hour** | **14 May** |
| **12** | **Indonesia as 4th country** | **MEDIUM** | **30 min** | **14 May** |
| **13** | **Final submission check (10 items)** | **CRITICAL** | **1 hour** | **14 May** |

**Submit by:** 15 May 2026

---

## NOTES FOR CODEX — NEVER BREAK THESE RULES

- Always read CLAUDE.md and WORKFLOW.md before starting any task
- Never remove the "No Quote, No Score" rule
- Never score from Tier 3 sources
- Never remove the heuristic fallback
- temperature=0.0 always for Ollama — legal scoring must be deterministic
- The Streamlit UI must call run_pipeline() — never duplicate scoring logic
- Do not add OpenAI, Anthropic, or any paid cloud LLM
- Every confirmed score must have: source_url, article_ref, verbatim_quote, sha256
- UNCERTAIN is a valid output — never suppress it
- Keep extraction_method in output so ESCAP knows bundled vs real PDF
