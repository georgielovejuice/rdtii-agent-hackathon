from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from main import run_pipeline
from pipeline.authority import filter_scoreable, get_tier1_only, resolve_authority
from pipeline.reason import _call_ollama, _heuristic_classify, load_rubric, score_indicator
from pipeline.verify import verify_span


def test_no_quote_no_score(monkeypatch):
    indicator = load_rubric(6)["indicators"][3]
    article = {
        "id": "s28",
        "section": "Section 28",
        "text": "An organisation shall not transfer personal data outside Thailand.",
    }
    source_meta = {
        "url": "https://example.gov/law",
        "title": "Example Law",
        "tier": 1,
        "extraction_method": "beautifulsoup",
        "effective_date": "",
        "sha256": "abc123",
    }

    monkeypatch.setattr(
        "pipeline.reason._call_llm",
        lambda _prompt: json.dumps({
            "score": 0.5,
            "confidence": "MEDIUM",
            "verbatim_quote": "",
            "article_ref": "Section 28",
            "rationale": "No quote supplied.",
        }),
    )

    result = score_indicator(indicator, article, source_meta)

    assert result.human_review_required is True
    assert result.confidence == "UNCERTAIN"


def test_span_verifier_catches_hallucination():
    source = "An organisation shall not transfer personal data outside Thailand."
    fake_quote = "Data must remain within national borders at all times."

    result = verify_span(fake_quote, source)

    assert result.passed is False
    assert result.confidence == "UNCERTAIN"


def test_span_verifier_passes_exact_match():
    source = "An organisation shall not transfer personal data outside Thailand."
    real_quote = "shall not transfer personal data outside Thailand"

    result = verify_span(real_quote, source)

    assert result.passed is True


def test_tier3_not_scored():
    doc = {
        "url": "https://example.gov/guideline",
        "title": "ETDA Guideline",
        "tier": 3,
        "language": "en",
        "doc_type": "html",
        "articles": [{"id": "g1", "section": "G1", "text": "Guidance only."}],
        "effective_date": "",
        "sha256": "",
    }

    resolved = resolve_authority([doc])

    assert resolved[0].scoreable is False
    assert resolved[0].extraction_method == ""
    assert filter_scoreable(resolved) == []


def test_tier1_wins_conflict():
    doc1 = {
        "url": "https://example.gov/law",
        "title": "Official Law",
        "tier": 1,
        "language": "en",
        "doc_type": "html",
        "articles": [{"id": "s28", "section": "Section 28", "text": "shall not transfer personal data"}],
        "effective_date": "",
        "sha256": "one",
    }
    doc2 = {
        "url": "https://example.gov/amendment",
        "title": "Official Amendment",
        "tier": 2,
        "language": "en",
        "doc_type": "pdf",
        "articles": [{"id": "s28", "section": "Section 28", "text": "data transfers require prior approval from authority"}],
        "effective_date": "",
        "sha256": "two",
    }

    resolved = resolve_authority([doc1, doc2])

    assert all(doc.conflict_flag for doc in resolved)
    assert get_tier1_only(resolved)[0].tier == 1


def test_heuristic_classifier_no_quote_no_score():
    indicator = load_rubric(6)["indicators"][0]

    result = _heuristic_classify(indicator, "This article is unrelated.", "Section 1")

    assert result["verbatim_quote"] == ""
    assert result["confidence"] == "UNCERTAIN"


def test_heuristic_finds_exact_phrase_thailand():
    text = (
        "the data controller shall not transfer any personal data to a foreign "
        "country, the destination country shall have adequate data protection standard"
    )
    indicator = load_rubric(6)["indicators"][3]

    result = _heuristic_classify(indicator, text, "Section 28")

    assert result["score"] is not None
    assert result["verbatim_quote"] in text


def test_end_to_end_thailand_offline(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("pipeline.reason._call_llm", lambda _prompt: None)

    all_scores = run_pipeline("thailand", [6, 7])

    assert len(all_scores) > 0
    assert any(score.confidence != "UNCERTAIN" for score in all_scores)
    assert all(score.verbatim_quote for score in all_scores if score.confidence != "UNCERTAIN")
    assert all(score.source_url for score in all_scores if score.confidence != "UNCERTAIN")
    dataset_path = Path("outputs/thailand_rdtii_dataset.jsonld")
    assert dataset_path.exists()
    dataset = json.loads(dataset_path.read_text())
    confirmed = [
        item for item in dataset["rdtii:indicators"]
        if item["confidence"] != "UNCERTAIN"
    ]
    assert all("extraction_method" in item for item in confirmed)


@pytest.mark.parametrize("country", ["vietnam", "singapore"])
def test_end_to_end_additional_demo_countries_offline(monkeypatch, country):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("pipeline.reason._call_llm", lambda _prompt: None)

    all_scores = run_pipeline(country, [6, 7])

    assert len(all_scores) > 0
    assert any(score.confidence != "UNCERTAIN" for score in all_scores)
    assert all(score.verbatim_quote for score in all_scores if score.confidence != "UNCERTAIN")
    assert all(score.source_url for score in all_scores if score.confidence != "UNCERTAIN")
    dataset_path = Path(f"outputs/{country}_rdtii_dataset.jsonld")
    dataset = json.loads(dataset_path.read_text())
    assert dataset["rdtii:country"] == country


def test_jsonld_shape_and_audit_stages(monkeypatch, tmp_path):
    import pipeline.export as export_module

    output_dir = tmp_path / "outputs"
    audit_db = tmp_path / "audit" / "runs.sqlite"
    monkeypatch.setattr(export_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(export_module, "AUDIT_DB", audit_db)
    monkeypatch.setattr("pipeline.reason._call_llm", lambda _prompt: None)

    run_pipeline("thailand", [6, 7])

    dataset = json.loads((output_dir / "thailand_rdtii_dataset.jsonld").read_text())
    required_fields = {
        "@type",
        "rdtii:pillar",
        "rdtii:indicatorId",
        "rdtii:indicatorName",
        "score",
        "confidence",
        "verbatim_quote",
        "source_url",
        "rdtii:sourceTitle",
        "rdtii:sourceTier",
        "extraction_method",
        "article_ref",
        "rdtii:sha256",
        "human_review_required",
    }
    assert dataset["@type"] == "rdtii:RegulatoryAnalysis"
    assert dataset["rdtii:indicators"]
    assert all(required_fields <= set(item) for item in dataset["rdtii:indicators"])

    with sqlite3.connect(audit_db) as conn:
        stages = {
            row[0]
            for row in conn.execute("SELECT DISTINCT stage FROM audit").fetchall()
        }
    assert {"discover", "extract", "authority", "retrieval", "reason", "export"} <= stages


def test_ollama_fallback_on_connection_error(monkeypatch):
    """
    If Ollama is not running, _call_ollama() must return None
    and the pipeline must fall back to heuristic — never crash.
    """
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:19999/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setattr("pipeline.reason._OLLAMA_UNAVAILABLE", False)

    result = _call_ollama("Return {}")

    assert result is None
