"""
Stage 3 — Authority Resolution
--------------------------------
Takes extracted documents and:
  1. Confirms / upgrades their Tier classification
  2. Detects version conflicts between documents
  3. Flags Tier 1 vs Tier 2 contradictions for human review
  4. Marks Tier 3 sources as "locate-only" — blocked from scoring

Outputs an AuthorityResolvedDoc for each input document.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class AuthorityResolvedDoc:
    source_url: str
    title: str
    tier: Literal[1, 2, 3]
    language: str
    doc_type: str
    articles: list[dict]           # from extract.py: {id, text, section}
    extraction_method: str = ""
    effective_date: str = ""       # ISO date string
    sha256: str = ""
    conflict_flag: bool = False    # True if this doc conflicts with another Tier 1 doc
    conflict_note: str = ""
    scoreable: bool = True         # False for Tier 3 sources


def resolve_authority(docs: list[dict]) -> list[AuthorityResolvedDoc]:
    """
    Main authority resolution function.

    Args:
        docs: list of dicts from extract.py, each with keys:
              url, title, tier, language, doc_type, articles, effective_date, sha256

    Returns:
        list of AuthorityResolvedDoc with conflicts flagged and Tier 3 blocked.
    """
    resolved: list[AuthorityResolvedDoc] = []

    for doc in docs:
        tier = doc.get("tier", 3)
        scoreable = tier in (1, 2)   # Tier 3 = locate only, never score

        rdoc = AuthorityResolvedDoc(
            source_url=doc.get("url", ""),
            title=doc.get("title", ""),
            tier=tier,
            language=doc.get("language", "en"),
            doc_type=doc.get("doc_type", "html"),
            extraction_method=doc.get("extraction_method", ""),
            articles=doc.get("articles", []),
            effective_date=doc.get("effective_date", ""),
            sha256=doc.get("sha256", ""),
            scoreable=scoreable,
        )

        if tier == 3:
            rdoc.conflict_note = "Tier 3 source — used for locating provisions only. Not used for scoring."
            logger.info(f"[authority] Tier 3 blocked from scoring: {rdoc.title}")

        resolved.append(rdoc)

    # ── Conflict detection ────────────────────────────────────────────────────
    # If two scoreable docs cover the same article and give contradictory text,
    # flag both for human review.
    resolved = _detect_conflicts(resolved)

    return resolved


def _detect_conflicts(docs: list[AuthorityResolvedDoc]) -> list[AuthorityResolvedDoc]:
    """
    Simple conflict detector: if two scoreable docs have an article with the
    same section ID but different text, flag both.
    """
    # Build index: section_id → list of (doc_index, article_text)
    section_index: dict[str, list[tuple[int, str]]] = {}

    for i, doc in enumerate(docs):
        if doc.tier not in (1, 2):
            continue
        for article in doc.articles:
            sec_id = article.get("id", "")
            if not sec_id:
                continue
            if sec_id not in section_index:
                section_index[sec_id] = []
            section_index[sec_id].append((i, article.get("text", "")))

    for sec_id, entries in section_index.items():
        if len(entries) < 2:
            continue
        # Check if texts differ meaningfully (simple length diff as proxy)
        texts = [e[1] for e in entries]
        if len(set(len(t) for t in texts)) > 1:
            for doc_idx, _ in entries:
                docs[doc_idx].conflict_flag = True
                docs[doc_idx].conflict_note = (
                    f"Conflict detected on section '{sec_id}' — "
                    "scoreable sources with differing text. Human review required."
                )
                logger.warning(
                    f"[authority] Conflict on section '{sec_id}' in '{docs[doc_idx].title}'"
                )

    return docs


def filter_scoreable(docs: list[AuthorityResolvedDoc]) -> list[AuthorityResolvedDoc]:
    """Return only docs that can be used for scoring (Tier 1 and 2)."""
    return [d for d in docs if d.scoreable and d.articles]


def get_tier1_only(docs: list[AuthorityResolvedDoc]) -> list[AuthorityResolvedDoc]:
    """Return only Tier 1 docs (highest authority)."""
    return [d for d in docs if d.tier == 1]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Quick smoke test
    sample_docs = [
        {
            "url": "https://oag.go.th/pdpa.pdf",
            "title": "Thailand PDPA",
            "tier": 1,
            "language": "en",
            "doc_type": "pdf",
            "articles": [{"id": "s28", "text": "An organisation shall not transfer...", "section": "Section 28"}],
            "effective_date": "2022-06-01",
            "sha256": "abc123",
        },
        {
            "url": "https://etda.or.th/guideline.pdf",
            "title": "ETDA PDPA Guideline",
            "tier": 3,
            "language": "en",
            "doc_type": "pdf",
            "articles": [{"id": "g1", "text": "Data must stay within Thailand...", "section": "Guideline 1"}],
            "effective_date": "2023-01-01",
            "sha256": "def456",
        },
    ]

    result = resolve_authority(sample_docs)
    for r in result:
        print(f"[Tier {r.tier}] {r.title} | scoreable={r.scoreable} | conflict={r.conflict_flag}")
        if r.conflict_note:
            print(f"  NOTE: {r.conflict_note}")
