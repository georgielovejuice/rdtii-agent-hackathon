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
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

from pipeline.verify import verify_span, VerificationResult

logger = logging.getLogger(__name__)

RUBRIC_DIR = Path(__file__).parent.parent / "rubrics"
OLLAMA_DEFAULT_MODEL = "llama3.1:8b"
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "20"))
_OLLAMA_UNAVAILABLE = False


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
    extraction_method: str
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

    # ── Call Ollama only for plausibly relevant article/indicator pairs ──────
    raw_response = _call_llm(prompt) if _is_relevant_for_llm(indicator, article_text) else None
    mode = "LLM:ollama"

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
        heuristic_score = _verified_heuristic_score(
            indicator,
            article_text,
            article_ref,
            source_meta,
            pillar_num,
        )
        if heuristic_score:
            logger.info(
                f"[reason] Verified heuristic fallback recovered indicator {indicator['id']} "
                f"after UNCERTAIN LLM result."
            )
            return heuristic_score
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
            extraction_method=source_meta.get("extraction_method", ""),
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
        heuristic_result = _verified_heuristic_score(
            indicator,
            article_text,
            article_ref,
            source_meta,
            pillar_num,
        )
        if heuristic_result:
            logger.info(
                f"[reason] Verified heuristic fallback recovered indicator {indicator['id']} "
                f"after unverified LLM quote."
            )
            return heuristic_result
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
            extraction_method=source_meta.get("extraction_method", ""),
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
        extraction_method=source_meta.get("extraction_method", ""),
        article_ref=article_ref,
        effective_date=source_meta.get("effective_date", ""),
        sha256=source_meta.get("sha256", ""),
        rationale=rationale,
        human_review_required=False,
        verification=verification,
    )


def _verified_heuristic_score(
    indicator: dict,
    article_text: str,
    article_ref: str,
    source_meta: dict,
    pillar_num: int,
) -> ScoredIndicator | None:
    """Return a heuristic score only when its exact quote verifies against source text."""
    heuristic = _heuristic_classify(indicator, article_text, article_ref)
    heuristic_score = heuristic.get("score")
    heuristic_quote = heuristic.get("verbatim_quote", "")
    if heuristic_score is None or not heuristic_quote:
        return None

    heuristic_verification = verify_span(
        llm_quote=heuristic_quote,
        source_text=article_text,
        llm_entities=_extract_entities(heuristic_quote, article_ref),
    )
    if not heuristic_verification.passed:
        return None

    return ScoredIndicator(
        pillar=pillar_num,
        indicator_id=indicator["id"],
        indicator_name=indicator["name"],
        score=float(heuristic_score),
        confidence=heuristic_verification.confidence,
        verbatim_quote=heuristic_quote,
        source_url=source_meta.get("url", ""),
        source_title=source_meta.get("title", ""),
        source_tier=source_meta.get("tier", 1),
        extraction_method=source_meta.get("extraction_method", ""),
        article_ref=article_ref,
        effective_date=source_meta.get("effective_date", ""),
        sha256=source_meta.get("sha256", ""),
        rationale=heuristic.get("rationale", ""),
        human_review_required=False,
        verification=heuristic_verification,
    )


def _call_llm(prompt: str) -> str | None:
    """Call the only supported LLM backend, returning None to trigger fallback."""
    return _call_ollama(prompt)


def _call_ollama(prompt: str) -> str | None:
    """
    Call Ollama through its native HTTP API.

    The server may be local or on a Tailscale address. Configure with:
      OLLAMA_BASE_URL=http://FRIEND_TAILSCALE_IP:11434
      OLLAMA_MODEL=llama3.1:8b
    """
    global _OLLAMA_UNAVAILABLE
    if _OLLAMA_UNAVAILABLE:
        return None

    base_url = _ollama_base_url()
    model = os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "num_predict": 512,
        },
    }
    request = urllib.request.Request(
        url=urljoin(f"{base_url}/", "api/chat"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("message", {}).get("content", "").strip() or None
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        _OLLAMA_UNAVAILABLE = True
        logger.error(f"[reason] Ollama API call failed: {e}")
        logger.info("[reason] Falling back to heuristic classifier for this run.")
        return None


def _ollama_base_url() -> str:
    """Return normalized Ollama base URL."""
    base_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_BASE_URL).strip().rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return base_url


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


def _is_relevant_for_llm(indicator: dict, article_text: str) -> bool:
    """
    Cheap pre-filter before expensive LLM calls.

    The heuristic fallback still runs when this returns False, so exact demo
    scoring remains available without spending an Ollama request on unrelated
    articles.
    """
    text = (article_text or "").lower()
    if not text.strip():
        return False

    keywords = [kw.lower() for kw in indicator.get("keywords", []) if kw]
    if any(keyword in text for keyword in keywords):
        return True

    rule_phrases = [phrase.lower() for _, phrase in _heuristic_rules().get(indicator["id"], [])]
    return any(phrase in text for phrase in rule_phrases)


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
        extraction_method=source_meta.get("extraction_method", ""),
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

    rules = _heuristic_rules()

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
    escaped_parts = [re.escape(part) for part in phrase.split()]
    pattern = r"\s+".join(escaped_parts)
    match = re.search(pattern, text, re.IGNORECASE)
    return text[match.start():match.end()] if match else ""


def _heuristic_rules() -> dict[str, list[tuple[float, str]]]:
    """Exact phrase rules used by the offline classifier and LLM pre-filter."""
    return {
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
            (0.0, "This Act applies to the collection, use, or disclosure of Personal Data"),
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
