"""
Stage 4b — Span Verifier (Anti-Hallucination)
----------------------------------------------
After the LLM produces a classification + verbatim quote,
this module verifies that the quote is ACTUALLY present in the source text.

Inspired by HalluGraph (2025): Entity Grounding + Relation Preservation checks.

Rules:
  - If the exact quote is not found verbatim → FAIL → UNCERTAIN
  - If key entities (article numbers, law names, dates) in the LLM output
    are not present in the source → FAIL → UNCERTAIN
  - Only PASS results proceed to scoring output
"""

from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85   # quote must match source at >= 85% similarity


@dataclass
class VerificationResult:
    passed: bool
    confidence: Literal["HIGH", "MEDIUM", "UNCERTAIN"]
    quote_found: bool
    similarity_score: float
    entities_grounded: bool
    failure_reason: str = ""


def verify_span(
    llm_quote: str,
    source_text: str,
    llm_entities: list[str] | None = None,
) -> VerificationResult:
    """
    Verify that the LLM's quoted span is genuinely present in the source text.

    Args:
        llm_quote:    The verbatim quote the LLM claims to have extracted.
        source_text:  The full source document text to check against.
        llm_entities: Key entities the LLM mentioned (article numbers, law names, dates).

    Returns:
        VerificationResult with pass/fail and confidence level.
    """
    if not llm_quote or not llm_quote.strip():
        return VerificationResult(
            passed=False,
            confidence="UNCERTAIN",
            quote_found=False,
            similarity_score=0.0,
            entities_grounded=False,
            failure_reason="LLM returned empty quote — No Quote, No Score rule triggered.",
        )

    # ── Step 1: Exact match check ─────────────────────────────────────────────
    clean_quote  = _normalize(llm_quote)
    clean_source = _normalize(source_text)

    if clean_quote in clean_source:
        quote_found = True
        similarity  = 1.0
        logger.info(f"[verify] Exact match found for quote: '{llm_quote[:60]}...'")
    else:
        # ── Step 2: Fuzzy match (catches minor OCR/whitespace differences) ────
        similarity  = _fuzzy_match(clean_quote, clean_source)
        quote_found = similarity >= SIMILARITY_THRESHOLD
        if quote_found:
            logger.info(f"[verify] Fuzzy match {similarity:.2f} for quote: '{llm_quote[:60]}...'")
        else:
            logger.warning(f"[verify] Quote NOT found (similarity={similarity:.2f}): '{llm_quote[:60]}...'")

    # ── Step 3: Entity grounding check ───────────────────────────────────────
    entities_grounded = True
    ungrounded = []
    if llm_entities:
        for entity in llm_entities:
            if _normalize(entity) not in clean_source:
                entities_grounded = False
                ungrounded.append(entity)
                logger.warning(f"[verify] Entity not found in source: '{entity}'")

    # ── Step 4: Final verdict ─────────────────────────────────────────────────
    if not quote_found:
        return VerificationResult(
            passed=False,
            confidence="UNCERTAIN",
            quote_found=False,
            similarity_score=similarity,
            entities_grounded=entities_grounded,
            failure_reason=(
                f"Quote not found in source (similarity={similarity:.2f}). "
                "Possible hallucination — routing to human review."
            ),
        )

    if not entities_grounded:
        return VerificationResult(
            passed=False,
            confidence="UNCERTAIN",
            quote_found=True,
            similarity_score=similarity,
            entities_grounded=False,
            failure_reason=(
                f"Quote found but entities not grounded: {ungrounded}. "
                "Possible entity substitution hallucination."
            ),
        )

    # Both checks passed
    confidence = "HIGH" if similarity >= 0.98 else "MEDIUM"
    return VerificationResult(
        passed=True,
        confidence=confidence,
        quote_found=True,
        similarity_score=similarity,
        entities_grounded=True,
    )


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation variations."""
    text = text.lower()
    text = text.translate(str.maketrans({
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2014": "-",
        "\u2013": "-",
        "\u00a0": " ",
    }))
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text


def _fuzzy_match(query: str, source: str) -> float:
    """
    Sliding window fuzzy match — find the best similarity score
    of the query against any window of the source of the same length.
    """
    q_len = len(query)
    if q_len == 0 or len(source) == 0:
        return 0.0

    if q_len > len(source):
        return SequenceMatcher(None, query, source).ratio()

    best = 0.0
    step = max(1, q_len // 4)   # slide in quarter-query steps for speed

    for i in range(0, len(source) - q_len + 1, step):
        window = source[i : i + q_len]
        score  = SequenceMatcher(None, query, window).ratio()
        if score > best:
            best = score
        if best >= 0.99:
            break   # close enough — stop early

    return best


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    source = (
        "Section 28. An organisation shall not transfer any personal data to a country "
        "or territory outside Thailand unless that country or territory has adequate "
        "personal data protection standards as prescribed by the Committee."
    )

    # Test 1: exact quote → should PASS
    result = verify_span(
        llm_quote="An organisation shall not transfer any personal data to a country or territory outside Thailand",
        source_text=source,
        llm_entities=["Section 28", "Thailand"],
    )
    print(f"Test 1 — passed={result.passed} | confidence={result.confidence} | sim={result.similarity_score:.2f}")

    # Test 2: hallucinated quote → should FAIL
    result2 = verify_span(
        llm_quote="Data must be stored within Thailand at all times without exception",
        source_text=source,
        llm_entities=["Section 28"],
    )
    print(f"Test 2 — passed={result2.passed} | confidence={result2.confidence} | reason={result2.failure_reason}")
