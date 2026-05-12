# CODEX PROMPTS - Current RDTII Agent Build Plan

Updated: 2026-05-12

This file replaces the older multi-provider prompt history. The active project
direction is now simpler and more reliable for a data pipeline: one LLM
provider, one model target, deterministic fallback, and auditable outputs.

## Current Backend Policy

- Use Ollama only.
- Use `llama3.1:8b` only.
- Run Ollama on the local machine or on the friend's GPU machine over Tailscale.
- Configure the endpoint with `OLLAMA_BASE_URL`.
- Configure the model with `OLLAMA_MODEL=llama3.1:8b`.
- If Ollama is unavailable, fall back to the local heuristic classifier.
- Never add paid cloud LLM providers back into this project unless explicitly
  requested by the project owner.

## Core Commands

Local Ollama:

```bash
ollama serve
ollama pull llama3.1:8b
python main.py --country thailand --pillars 6 7
```

Friend GPU over Tailscale:

```bash
export OLLAMA_BASE_URL=http://FRIEND_TAILSCALE_IP:11434
export OLLAMA_MODEL=llama3.1:8b
python main.py --country thailand --pillars 6 7
```

All demo countries:

```bash
python main.py --country thailand --pillars 6 7
python main.py --country vietnam --pillars 6 7
python main.py --country singapore --pillars 6 7
```

Tests:

```bash
pytest tests/ -v
```

Browser UI:

```bash
streamlit run app.py
```

## Never-Break Rules

- No Quote -> No Score.
- Tier 3 sources are locate-only and never used for scoring.
- The LLM may classify one provision against one RDTII indicator and extract a
  verbatim quote; it may not freestyle, infer intent, or synthesize across
  sources.
- Every confirmed score must include a verbatim quote, source URL, article
  reference, source tier, document hash, and extraction method.
- Span verification must run before a score is accepted.
- `UNCERTAIN` is a valid result and must stay visible in the review queue.
- The pipeline must keep working without the LLM through heuristic fallback.
- The SQLite audit trail must keep logging all six pipeline stages.

## Current Next Tasks

1. Improve real PDF extraction so the project uses full legal documents more
   often and bundled fallback text less often.
2. Add keyword pre-filtering before LLM calls to reduce latency and load on the
   remote Ollama server.
3. Strengthen retrieval dependencies and fallback behavior for ChromaDB and
   NetworkX.
4. Continue keeping the Streamlit UI thin: it should call the backend pipeline
   and display existing JSON-LD, country brief, and review queue outputs.
5. Add database-backed ingestion later only after the current CLI/UI pipeline is
   stable.
