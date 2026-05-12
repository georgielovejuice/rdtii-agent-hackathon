"""
Stage 1 — Discovery
--------------------
Finds authoritative legal sources for a given country and pillar scope.

Outputs a list of DiscoveredSource objects, each with:
  - url
  - title
  - language
  - doc_type  (pdf | html | scanned_pdf)
  - tier      (1 | 2 | 3)
  - pillar_hint  (which pillar this source likely covers)
"""

from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Tier classification rules ─────────────────────────────────────────────────

# Tier 1 TLD/domain patterns  (official legislation & gazettes)
TIER1_PATTERNS = [
    r"\.go\.th",          # Thailand government
    r"\.gov\.sg",         # Singapore government
    r"\.gov\.vn",         # Vietnam government
    r"vanban\.chinhphu",  # Vietnam government legal document portal
    r"\.gov\.kz",         # Kazakhstan
    r"\.gov\.au",         # Australia
    r"oag\.go\.th",       # Thailand Office of the Attorney General
    r"ratchakitcha",      # Thailand Royal Gazette
    r"agc\.gov\.sg",      # Singapore Attorney General's Chambers
    r"moj\.go\.jp",       # Japan Ministry of Justice
    r"legislation\.",     # legislation.gov.uk etc.
    r"official-gazette",
    r"gazette\.",
]

# Tier 2 patterns  (amendments, implementing regulations)
TIER2_PATTERNS = [
    r"etda\.or\.th",      # Thailand ETDA (implementing body)
    r"pdpc\.gov\.sg",     # Singapore PDPC
    r"most\.gov\.vn",     # Vietnam Ministry of Science
    r"mict\.go\.th",      # Thailand MICT
    r"amendment",
    r"implementing",
    r"regulation",
    r"decree",
    r"ministerial",
]

# Tier 3 patterns  (guidelines, FAQs — locate only, never score)
TIER3_PATTERNS = [
    r"guideline",
    r"guidance",
    r"faq",
    r"factsheet",
    r"explainer",
    r"manual",
]


@dataclass
class DiscoveredSource:
    url: str
    title: str
    language: str                              # ISO 639-1 code, e.g. "th", "en"
    doc_type: Literal["pdf", "html", "scanned_pdf"]
    tier: Literal[1, 2, 3]
    pillar_hint: list[int] = field(default_factory=list)  # e.g. [6, 7]
    raw_text_preview: str = ""                 # first 500 chars for quick check
    sha256: str = ""                           # document hash (set after download)
    retrieved_at: str = ""                     # ISO datetime


def classify_tier(url: str, title: str = "") -> int:
    """
    Classify a URL into authority Tier 1, 2, or 3.
    Tier 1 = official legislation / gazette
    Tier 2 = implementing regulations / amendments
    Tier 3 = guidelines / FAQs (reference only, never scored)
    """
    combined = (url + " " + title).lower()

    for pattern in TIER3_PATTERNS:
        if re.search(pattern, combined):
            return 3

    for pattern in TIER1_PATTERNS:
        if re.search(pattern, combined):
            return 1

    for pattern in TIER2_PATTERNS:
        if re.search(pattern, combined):
            return 2

    # Default to Tier 3 if no match
    return 3


def infer_doc_type(url: str, content_type: str = "") -> Literal["pdf", "html", "scanned_pdf"]:
    """Guess document type from URL and Content-Type header."""
    url_lower = url.lower()
    ct_lower  = content_type.lower()

    if "pdf" in url_lower or "application/pdf" in ct_lower:
        return "pdf"       # may be scanned — extract.py will determine
    return "html"


# ── Seed URL database ─────────────────────────────────────────────────────────
# Known authoritative sources per country for Pillar 6 & 7.
# These are starting points — the crawler will discover more.

SEED_SOURCES: dict[str, list[dict]] = {
    "thailand": [
        {
            "url": "file:///home/engineerkim/Desktop/rdtii-agent/pdf/thailand/Personal%20Data%20Protection%20Act%202019.pdf",
            "title": "Personal Data Protection Act B.E. 2562 (2019) — local copy",
            "language": "en",
            "doc_type": "pdf",
            "tier": 1,
            "pillar_hint": [6, 7],
        },
        {
            "url": "https://www.oag.go.th/wp-content/uploads/2021/11/Personal-Data-Protection-Act-BE-2562-2019.pdf",
            "title": "Personal Data Protection Act B.E. 2562 (2019)",
            "language": "en",
            "doc_type": "pdf",
            "pillar_hint": [6, 7],
        },
        {
            "url": "https://www.ratchakitcha.soc.go.th/",
            "title": "Thailand Royal Gazette — PDPA",
            "language": "th",
            "doc_type": "html",
            "pillar_hint": [6, 7],
        },
        {
            "url": "https://www.etda.or.th/en/",
            "title": "ETDA — Electronic Transactions Development Agency",
            "language": "en",
            "doc_type": "html",
            "pillar_hint": [6],
        },
    ],
    "vietnam": [
        {
            "url": "https://vanban.chinhphu.vn/cybersecurity-law-24-2018-qh14",
            "title": "Vietnam Cybersecurity Law (Law 24/2018/QH14)",
            "language": "vi",
            "doc_type": "html",
            "pillar_hint": [6, 7],
        },
        {
            "url": "https://vanban.chinhphu.vn/decree-13-2023-nd-cp-personal-data-protection",
            "title": "Decree 13/2023/ND-CP on Personal Data Protection",
            "language": "vi",
            "doc_type": "html",
            "pillar_hint": [7],
        },
    ],
    "singapore": [
        {
            "url": "https://sso.agc.gov.sg/Act/PDPA2012",
            "title": "Personal Data Protection Act 2012 (No. 26 of 2012)",
            "language": "en",
            "doc_type": "html",
            "pillar_hint": [6, 7],
        },
        {
            "url": "https://www.pdpc.gov.sg/Overview-of-PDPA/The-Legislation/Personal-Data-Protection-Act",
            "title": "PDPC — PDPA Overview",
            "language": "en",
            "doc_type": "html",
            "pillar_hint": [6, 7],
        },
    ],
}


def get_seed_sources(country: str, pillars: list[int] | None = None) -> list[DiscoveredSource]:
    """
    Return pre-seeded authoritative sources for a country.
    Filter by pillar_hint if pillars is specified.
    """
    country_key = country.lower().strip()
    raw = SEED_SOURCES.get(country_key, [])

    sources = []
    for item in raw:
        if pillars and not any(p in item.get("pillar_hint", []) for p in pillars):
            continue
        tier = item.get("tier", classify_tier(item["url"], item["title"]))
        sources.append(DiscoveredSource(
            url=item["url"],
            title=item["title"],
            language=item.get("language", "en"),
            doc_type=item["doc_type"],
            tier=tier,
            pillar_hint=item.get("pillar_hint", []),
        ))

    logger.info(f"[discover] Loaded {len(sources)} seed sources for '{country}'")
    return sources


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sources = get_seed_sources("thailand", pillars=[6, 7])
    for s in sources:
        print(f"[Tier {s.tier}] {s.title} — {s.url}")
