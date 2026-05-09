"""
Stage 5 — Legal Reasoning Chain
---------------------------------
The constrained LLM scoring engine.

For each RDTII indicator (Pillar 6 or 7), for each article chunk:
  1. Load the hardcoded rubric from rubrics/pillar{N}.json
  2. Build a constrained prompt — LLM can ONLY classify + quote, never freestyle
  3. Call the configured LLM backend
  4. Parse structured response (score, quote, confidence, rationale)
  5. Pass quote to verify.py for span verification
  6. Return ScoredIndicator with full citation metadata

The LLM is a classifier constrained by a rubric.
It is NOT a free-form interpreter.
"""

from __future__ import annotations
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pipeline.verify import verify_span, VerificationResult

logger = logging.getLogger(__name__)

RUBRIC_DIR = Path(__file__).parent.parent / "rubrics"
BACKEND    = os.getenv("LLM_BACKEND", "ollama").lower()


@dataclass
class ScoredIndicator:
    pillar: int
    indicator_id: str
    indicator_name: str
    score: float                              # 0.0 to 1.0
    confidence: Literal["HIGH", "MEDIUM", "UNCERTAIN"]
    verbatim_quote: str                       # exact text from source
    source_url: str
    source_title: str
    source_tier: int
    article_ref: str                          # e.g. "Section 28"
    effective_date: str
    sha256: str
    rationale: str                            # LLM's one-sentence explanation
    human_review_required: bool = False
    human_review_reason: str = ""
    verification: VerificationResult | None = None


def load_rubric(pillar: int) -> dict:
    """Load the RDTII rubric JSON for a given pillar."""
    path = RUBRIC_DIR / f"pillar{pillar}.json"
    if not path.exists():
        raise FileNotFoundError(f"Rubric not found: {path}")
    with open(path) as f:
        return json.load(f)


def build_prompt(indicator: dict, article_text: str, article_ref: str) -> str:
    """
    Build the constrained scoring prompt.
    The LLM MUST:
      - Return a JSON object only
      - Quote verbatim from the provided text
      - Return UNCERTAIN if no supporting phrase exists
    """
    scoring_guide_text = "\n".join(
        f"  Score {score}: {desc}"
        for score, desc in indicator["scoring_guide"].items()
    )

    return f"""You are a regulatory analyst scoring a legal provision against the RDTII 2.0 framework.

INDICATOR TO SCORE:
  Pillar: {indicator.get('pillar_number', '?')}
  Indicator ID: {indicator['id']}
  Indicator Name: {indicator['name']}
  Description: {indicator['description']}

SCORING GUIDE:
{scoring_guide_text}

LEGAL TEXT TO ANALYSE:
  Article/Section: {article_ref}
  Text:
  ---
  {article_text}
  ---

INSTRUCTIONS (STRICT — do not deviate):
1. Determine whether this legal text addresses the indicator above.
2. If it does, assign a score from the scoring guide (0.0, 0.5, or 1.0).
3. You MUST quote the EXACT phrase from the legal text above that supports your score.
   - The quote must be copied verbatim — do not paraphrase.
   - The quote must exist word-for-word in the text above.
4. If the text does NOT address this indicator or you cannot find a supporting phrase,
   return score: null and confidence: "UNCERTAIN".
5. Do NOT infer intent. Do NOT combine this text with other sources.
6. Do NOT use knowledge outside the provided text.

Return ONLY a JSON object with this exact structure:
{{
  "score": <0.0 | 0.5 | 1.0 | null>,
  "confidence": <"HIGH" | "MEDIUM" | "UNCERTAIN">,
  "verbatim_quote": "<exact copied phrase from the text, or empty string if UNCERTAIN>",
  "article_ref": "{article_ref}",
  "rationale": "<one sentence explaining your score, max 30 words>"
}}

Return ONLY the JSON object. No preamble, no markdown fences, no ```json blocks, no explanation outside the JSON. Start your response with {{ and end with }}."""


def score_indicator(
    indicator: dict,
    article: dict,
    source_meta: dict,
) -> ScoredIndicator:
    """
    Score a single RDTII indicator against a single article chunk.

    Args:
        indicator:   One indicator dict from the pillar rubric JSON.
        article:     Dict with keys: id, text, section (from extract.py).
        source_meta: Dict with keys: url, title, tier, effective_date, sha256, language.

    Returns:
        ScoredIndicator with full citation and verification.
    """
    pillar_num = int(indicator["id"].split(".")[0])
    article_text = article.get("text", "")
    article_ref  = article.get("section", article.get("id", "Unknown section"))

    prompt = build_prompt(
        {**indicator, "pillar_number": pillar_num},
        article_text,
        article_ref,
    )

    # ── Call selected LLM backend, or deterministic local fallback ───────────
    raw_response = _call_llm(prompt)
    mode = f"LLM:{BACKEND}"

    if raw_response is None:
        parsed = _heuristic_classify(indicator, article_text, article_ref)
        mode = "heuristic"
    else:
        try:
            parsed = _parse_llm_response(raw_response)
            logger.debug(f"[reason] Raw LLM response: {raw_response[:200]}")
        except Exception as e:
            logger.error(f"[reason] Parse failed: {e} — heuristic fallback")
            parsed = _heuristic_classify(indicator, article_text, article_ref)
            mode = "heuristic"

    logger.info(
        f"[reason] [{mode}] Indicator {indicator['id']} → "
        f"{parsed.get('score')} ({parsed.get('confidence')})"
    )

    score       = parsed.get("score")
    confidence  = parsed.get("confidence", "UNCERTAIN")
    quote       = parsed.get("verbatim_quote", "")
    rationale   = parsed.get("rationale", "")

    # ── No Quote, No Score rule ───────────────────────────────────────────────
    if score is not None and (not quote or not quote.strip()):
        logger.warning(f"[reason] Score={score} but no quote provided — triggering No Quote, No Score rule")
        return _uncertain(
            indicator, source_meta, article_ref,
            "LLM provided score but no verbatim quote — No Quote, No Score rule triggered."
        )

    # ── UNCERTAIN from LLM ────────────────────────────────────────────────────
    if score is None or confidence == "UNCERTAIN":
        return ScoredIndicator(
            pillar=pillar_num,
            indicator_id=indicator["id"],
            indicator_name=indicator["name"],
            score=0.0,
            confidence="UNCERTAIN",
            verbatim_quote="",
            source_url=source_meta.get("url", ""),
            source_title=source_meta.get("title", ""),
            source_tier=source_meta.get("tier", 3),
            article_ref=article_ref,
            effective_date=source_meta.get("effective_date", ""),
            sha256=source_meta.get("sha256", ""),
            rationale=rationale or "LLM returned UNCERTAIN — no supporting phrase found.",
            human_review_required=True,
            human_review_reason="LLM could not find supporting evidence in this article.",
        )

    # ── Span verification ─────────────────────────────────────────────────────
    verification = verify_span(
        llm_quote=quote,
        source_text=article_text,
        llm_entities=_extract_entities(quote, article_ref),
    )

    if not verification.passed:
        logger.warning(
            f"[reason] Span verification FAILED for indicator {indicator['id']}: "
            f"{verification.failure_reason}"
        )
        return ScoredIndicator(
            pillar=pillar_num,
            indicator_id=indicator["id"],
            indicator_name=indicator["name"],
            score=0.0,
            confidence="UNCERTAIN",
            verbatim_quote=quote,
            source_url=source_meta.get("url", ""),
            source_title=source_meta.get("title", ""),
            source_tier=source_meta.get("tier", 3),
            article_ref=article_ref,
            effective_date=source_meta.get("effective_date", ""),
            sha256=source_meta.get("sha256", ""),
            rationale=rationale,
            human_review_required=True,
            human_review_reason=f"Span verification failed: {verification.failure_reason}",
            verification=verification,
        )

    # ── All checks passed — return scored result ──────────────────────────────
    logger.info(
        f"[reason] Indicator {indicator['id']} scored {score} ({confidence}) "
        f"from {article_ref} | quote: '{quote[:60]}...'"
    )
    return ScoredIndicator(
        pillar=pillar_num,
        indicator_id=indicator["id"],
        indicator_name=indicator["name"],
        score=float(score),
        confidence=verification.confidence,
        verbatim_quote=quote,
        source_url=source_meta.get("url", ""),
        source_title=source_meta.get("title", ""),
        source_tier=source_meta.get("tier", 1),
        article_ref=article_ref,
        effective_date=source_meta.get("effective_date", ""),
        sha256=source_meta.get("sha256", ""),
        rationale=rationale,
        human_review_required=False,
        verification=verification,
    )


def _call_llm(prompt: str) -> str | None:
    """Call the configured LLM backend, returning None to trigger fallback."""
    if BACKEND == "ollama":
        return _call_ollama(prompt)
    if BACKEND == "openai":
        return _call_openai(prompt)
    if BACKEND == "anthropic":
        return _call_anthropic(prompt)
    raise ValueError(f"Unknown LLM_BACKEND: {BACKEND}")


def _call_ollama(prompt: str) -> str | None:
    """
    Call a local Ollama server via its OpenAI-compatible API.
    Ollama must be running: `ollama serve`
    Model must be pulled: `ollama pull qwen2.5:3b`
    """
    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        logger.warning("[reason] openai package not installed — falling back to heuristic")
        return None

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OLLAMA_MODEL", os.getenv("LLM_MODEL", "qwen2.5:3b"))
    if model in {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3", "claude-sonnet-4-20250514"}:
        model = "qwen2.5:3b"

    try:
        client = OpenAI(
            api_key="ollama",
            base_url=base_url,
        )
        response = client.chat.completions.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[reason] Ollama API call failed: {e}")
        logger.info("[reason] Is Ollama running? Try: ollama serve")
        return None


def _call_openai(prompt: str) -> str | None:
    """Call OpenAI chat completions with JSON-object response mode."""
    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        logger.warning("[reason] openai package not installed — falling back to heuristic")
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[reason] OPENAI_API_KEY not set — falling back to heuristic")
        return None

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o"),
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[reason] OpenAI API call failed: {e}")
        return None


def _call_anthropic(prompt: str) -> str | None:
    """Call Anthropic messages API."""
    try:
        import anthropic as anthropic_sdk
    except ModuleNotFoundError:
        logger.warning("[reason] anthropic package not installed — falling back to heuristic")
        return None

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[reason] ANTHROPIC_API_KEY not set — falling back to heuristic")
        return None

    try:
        client = anthropic_sdk.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=os.getenv("LLM_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"[reason] Anthropic API call failed: {e}")
        return None


def _parse_llm_response(raw: str) -> dict:
    """Parse a JSON object from an LLM response with common formatting cleanup."""
    cleaned = raw.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in LLM response")

    cleaned = cleaned[start : end + 1]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    parsed = json.loads(cleaned)

    if parsed.get("score") is not None:
        parsed["score"] = float(parsed["score"])

    return parsed


def _uncertain(
    indicator: dict,
    source_meta: dict,
    article_ref: str,
    reason: str,
) -> ScoredIndicator:
    """Return a safe UNCERTAIN result."""
    pillar_num = int(indicator["id"].split(".")[0])
    return ScoredIndicator(
        pillar=pillar_num,
        indicator_id=indicator["id"],
        indicator_name=indicator["name"],
        score=0.0,
        confidence="UNCERTAIN",
        verbatim_quote="",
        source_url=source_meta.get("url", ""),
        source_title=source_meta.get("title", ""),
        source_tier=source_meta.get("tier", 3),
        article_ref=article_ref,
        effective_date=source_meta.get("effective_date", ""),
        sha256=source_meta.get("sha256", ""),
        rationale=reason,
        human_review_required=True,
        human_review_reason=reason,
    )


def uncertain_indicator(indicator: dict, reason: str) -> ScoredIndicator:
    """Return an indicator-level UNCERTAIN result when retrieval found no source."""
    return _uncertain(
        indicator=indicator,
        source_meta={"tier": 3},
        article_ref="No source retrieved",
        reason=reason,
    )


def _extract_entities(quote: str, article_ref: str) -> list[str]:
    """
    Extract key entities from a quote for entity grounding check.
    Simple heuristic: section numbers, law names, dates.
    """
    entities = []
    if article_ref and article_ref.lower() not in {"document title", "document", "unknown section"}:
        entities.append(article_ref)
    # Section/Article numbers
    entities += re.findall(r"\b(?:Section|Article|s\.|Art\.)\s*\d+[\w.]*", quote, re.IGNORECASE)
    # Years (law dates)
    entities += re.findall(r"\b(19|20)\d{2}\b", quote)
    return list(set(entities))


def _heuristic_classify(indicator: dict, article_text: str, article_ref: str) -> dict:
    """
    Deterministic fallback classifier for offline demos.

    It uses only exact spans from the supplied article text and returns
    UNCERTAIN unless a narrow indicator-specific trigger is present.
    """
    text = article_text or ""
    low = text.lower()
    ind_id = indicator["id"]

    rules = {
        "6.1": [
            (0.5, "shall have adequate data protection standard"),
            (0.5, "may send or transfer the personal data to a foreign country where the data subject has given consent"),
            (1.0, "set up branches or representative offices in Vietnam"),
        ],
        "6.2": [
            (1.0, "shall store such data in Vietnam for a prescribed period of time"),
            (1.0, "store data in Vietnam for a period of time as prescribed by the Government"),
        ],
        "6.4": [
            (0.5, "shall have adequate data protection standard"),
            (0.5, "data subject has given consent after having been informed"),
            (0.5, "consented to by the data subject and meet the conditions prescribed"),
            (0.5, "assess the impact of transferring personal data overseas"),
            (0.5, "must not transfer personal data to a country or territory outside Singapore except"),
            (0.5, "comparable to the protection under this Act"),
        ],
        "7.1": [
            (0.0, "Personal Data Protection Act B.E. 2562"),
            (0.0, "Personal Data Protection Act B.E. 2562 (2019)"),
            (0.0, "Decree 13/2023/ND-CP on Personal Data Protection"),
            (0.0, "Personal Data Protection Act 2012"),
        ],
        "7.2": [
            (0.0, "making reasonable security arrangements to prevent unauthorised access"),
        ],
        "7.3": [
            (0.5, "shall designate a data protection officer"),
            (0.5, "require regular monitoring of personal data"),
        ],
        "7.4": [
            (0.5, "enter the premises of the data controller or data processor during working hours for the purpose of inspection"),
            (0.5, "seize or attach documents, evidence or any other things"),
        ],
    }

    for score, phrase in rules.get(ind_id, []):
        quote = _exact_phrase(text, phrase)
        if quote:
            return {
                "score": score,
                "confidence": "MEDIUM",
                "verbatim_quote": quote,
                "article_ref": article_ref,
                "rationale": "Local classifier found an exact provision matching the indicator.",
            }

    keyword_hits = [
        kw for kw in indicator.get("keywords", [])
        if kw.lower() in low
    ]
    if keyword_hits:
        return {
            "score": None,
            "confidence": "UNCERTAIN",
            "verbatim_quote": "",
            "article_ref": article_ref,
            "rationale": f"Keyword match only ({', '.join(keyword_hits[:3])}); no scoring rule matched.",
        }

    return {
        "score": None,
        "confidence": "UNCERTAIN",
        "verbatim_quote": "",
        "article_ref": article_ref,
        "rationale": "No supporting phrase found in this article.",
    }


def _exact_phrase(text: str, phrase: str) -> str:
    """Return the exact source substring matching phrase case-insensitively."""
    match = re.search(re.escape(phrase), text, re.IGNORECASE)
    return text[match.start():match.end()] if match else ""
