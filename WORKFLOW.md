# RDTII Agent Workflow

Last updated: 2026-05-12

This workflow describes how to run, extend, test, and checkpoint the current
`rdtii-agent` repository. The active build policy is Ollama-only with
`llama3.1:8b`, plus deterministic heuristic fallback when Ollama is unavailable.

## 1. Prepare The Environment

Create and activate a Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For local Ollama:

```bash
ollama serve
ollama pull llama3.1:8b
export OLLAMA_MODEL=llama3.1:8b
```

For a friend's machine over Tailscale:

```bash
export OLLAMA_BASE_URL=http://FRIEND_TAILSCALE_IP:11434
export OLLAMA_MODEL=llama3.1:8b
```

If Ollama is not reachable, the pipeline still runs through the local heuristic
fallback. The fallback must keep enforcing "No Quote -> No Score".

ChromaDB semantic retrieval uses the local
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` embedding model.
The pipeline loads this model from the local cache by default so restricted demo
environments do not pause on Hugging Face retries. To download or refresh the
model intentionally, run once with:

```bash
RDTII_ALLOW_EMBEDDING_DOWNLOAD=true python -c "from pipeline.retrieval import _get_embedder; _get_embedder()"
```

## 2. Collect Official Source Documents

Start with official Tier 1 or Tier 2 sources. For the current demo, prioritize:

- Thailand: PDPA, digital government, cybersecurity, AI/data economy documents.
- Vietnam: personal data protection decree, cybersecurity law, digital
  transformation strategy.
- Singapore: PDPA, PDPC/IMDA materials, Smart Nation, AI governance,
  cybersecurity materials.

When a government site blocks automated download, manually download the PDF and
reference it with a `file://` URL:

```text
file:///home/engineerkim/Downloads/thailand_pdpa.pdf
```

Tier 3 materials may help locate provisions, but they must not be used as final
scoring evidence.

## 3. Add Or Update Sources

Source seeds live in `pipeline/discover.py`.

Each source should include:

- `url`: official URL or absolute `file://` URL.
- `title`: clear legal or policy title.
- `language`: document language when known.
- `doc_type`: usually `pdf` or `html`.
- `pillar_hint`: `[6]`, `[7]`, or `[6, 7]`.

Keep source additions narrow and official. Do not add broad web pages as scoring
sources unless they are authoritative legal or regulatory pages.

## 4. Run The Pipeline

Run one country first:

```bash
python main.py --country thailand --pillars 6 7
```

Then run all demo countries:

```bash
python main.py --country thailand --pillars 6 7
python main.py --country vietnam --pillars 6 7
python main.py --country singapore --pillars 6 7
```

Generated outputs are written under `outputs/` by default:

- `<country>_rdtii_dataset.jsonld`
- `<country>_country_brief.md`
- `<country>_review_queue.json`
- `rdtii_audit.db`

## 5. Review Evidence Quality

For every confirmed score, check that the output includes:

- Verbatim quote.
- Article or section reference.
- Source title.
- Source URL or file reference.
- Authority tier.
- SHA256 document hash.
- Extraction method.
- Human review flag set to false.

If a score lacks reliable evidence, it should be `UNCERTAIN` and appear in the
review queue.

## 6. Test The Project

Run the full test suite:

```bash
pytest tests/ -v
```

Validate generated JSON-LD when outputs change:

```bash
python -m json.tool outputs/thailand_rdtii_dataset.jsonld
python -m json.tool outputs/vietnam_rdtii_dataset.jsonld
python -m json.tool outputs/singapore_rdtii_dataset.jsonld
```

Check audit stages when pipeline behavior changes:

```bash
sqlite3 outputs/rdtii_audit.db "select distinct stage from audit_log order by stage;"
```

Expected stages are:

```text
authority
discover
export
extract
reason
retrieval
```

## 7. Use The Streamlit UI

Start the UI after installing dependencies:

```bash
streamlit run app.py
```

The UI should stay thin. It should call the existing backend pipeline and
display generated JSON-LD, country brief, and review queue files instead of
duplicating scoring logic.

## 8. Development Rules

Keep the codebase reliable and pipeline-oriented:

- Use structured functions for each pipeline stage.
- Keep source metadata attached as it moves through the pipeline.
- Prefer deterministic behavior for scoring and verification.
- Keep Ollama calls behind relevance filtering and timeouts.
- Keep embedding model downloads explicit with
  `RDTII_ALLOW_EMBEDDING_DOWNLOAD=true`.
- Keep heuristic fallback functional for offline demos.
- Do not add OpenAI, Anthropic, or other paid cloud LLM providers.
- Do not accept scores from Tier 3 sources.
- Do not bypass span verification for confirmed outputs.

## 9. Agent Checkpoint Workflow

Every coding agent edit must follow this sequence:

1. Inspect the relevant files and current `git status`.
2. Make the smallest coherent change.
3. Update `AGENTS.md` in the same turn.
4. Run relevant tests or explain why tests were not run.
5. Commit the change as a checkpoint.

Suggested commit format:

```bash
git add <changed-files>
git commit -m "docs: add repository workflow"
```

## 10. Recommended Next Build Path

The current backend is demo-ready. The next useful work is:

1. Add real official `file://` PDFs for Thailand first.
2. Verify extraction quality and quote coverage from those PDFs.
3. Expand Vietnam and Singapore real-source coverage.
4. Improve retrieval dependency behavior only after source ingestion is stable.
5. Keep the UI focused on running the backend and reviewing evidence.
