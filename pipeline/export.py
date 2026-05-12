"""
Stage 6 — Verified Output
--------------------------
Takes scored indicators and produces:
  1. JSON-LD dataset  (machine-readable, UN-compatible linked data)
  2. Country brief    (Jinja2 Markdown → PDF, ESCAP format)
  3. SQLite audit trail (every pipeline decision logged)
  4. Human review queue (UNCERTAIN items flagged for expert review)
"""

from __future__ import annotations
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./outputs"))
AUDIT_DB   = Path(os.getenv("AUDIT_DB", "./outputs/audit/runs.sqlite"))
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "country_brief.md.j2"


# ── JSON-LD Export ────────────────────────────────────────────────────────────

def export_jsonld(
    country: str,
    scores: list,         # list of ScoredIndicator
    run_id: str,
) -> Path:
    """Export scored indicators as a JSON-LD dataset."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    dataset = {
        "@context": {
            "@vocab": "https://unescap.org/rdtii/",
            "rdtii": "https://unescap.org/rdtii/",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "score": "rdtii:score",
            "confidence": "rdtii:confidence",
            "verbatim_quote": "rdtii:verbatimQuote",
            "source_url": "rdtii:sourceUrl",
            "extraction_method": "rdtii:extractionMethod",
            "article_ref": "rdtii:articleRef",
            "human_review_required": "rdtii:humanReviewRequired",
        },
        "@type": "rdtii:RegulatoryAnalysis",
        "rdtii:country": country,
        "rdtii:runId": run_id,
        "rdtii:generatedAt": datetime.now(timezone.utc).isoformat(),
        "rdtii:framework": "RDTII 2.0",
        "rdtii:indicators": [],
    }

    for s in scores:
        entry = {
            "@type": "rdtii:IndicatorScore",
            "rdtii:pillar": s.pillar,
            "rdtii:indicatorId": s.indicator_id,
            "rdtii:indicatorName": s.indicator_name,
            "score": s.score if not s.human_review_required else None,
            "confidence": s.confidence,
            "verbatim_quote": s.verbatim_quote,
            "source_url": s.source_url,
            "rdtii:sourceTitle": s.source_title,
            "rdtii:sourceTier": s.source_tier,
            "extraction_method": s.extraction_method,
            "article_ref": s.article_ref,
            "rdtii:effectiveDate": s.effective_date,
            "rdtii:sha256": s.sha256,
            "rdtii:rationale": s.rationale,
            "human_review_required": s.human_review_required,
            "rdtii:humanReviewReason": s.human_review_reason if s.human_review_required else None,
        }
        dataset["rdtii:indicators"].append(entry)

    out_path = OUTPUT_DIR / f"{country.lower()}_rdtii_dataset.jsonld"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    logger.info(f"[export] JSON-LD written → {out_path}")
    return out_path


# ── Human Review Queue ────────────────────────────────────────────────────────

def export_review_queue(
    country: str,
    scores: list,
    run_id: str,
) -> Path | None:
    """Export UNCERTAIN items as a human review queue JSON."""
    uncertain = [s for s in scores if s.human_review_required]
    if not uncertain:
        logger.info("[export] No uncertain items — no review queue needed")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    queue = {
        "run_id": run_id,
        "country": country,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_uncertain": len(uncertain),
        "items": [
            {
                "indicator_id": s.indicator_id,
                "indicator_name": s.indicator_name,
                "pillar": s.pillar,
                "reason": s.human_review_reason,
                "source_url": s.source_url,
                "extraction_method": s.extraction_method,
                "article_ref": s.article_ref,
                "verbatim_quote": s.verbatim_quote,
            }
            for s in uncertain
        ],
    }

    out_path = OUTPUT_DIR / f"{country.lower()}_review_queue.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

    logger.info(f"[export] Review queue ({len(uncertain)} items) → {out_path}")
    return out_path


# ── SQLite Audit Trail ────────────────────────────────────────────────────────

def log_to_audit(
    run_id: str,
    country: str,
    stage: str,
    action: str,
    detail: str,
    outcome: str = "OK",
):
    """Append one audit event to the SQLite audit trail."""
    AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUDIT_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id    TEXT,
            country   TEXT,
            stage     TEXT,
            action    TEXT,
            detail    TEXT,
            outcome   TEXT,
            ts        TEXT
        )
    """)
    conn.execute(
        "INSERT INTO audit (run_id, country, stage, action, detail, outcome, ts) VALUES (?,?,?,?,?,?,?)",
        (run_id, country, stage, action, detail, outcome, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


# ── Country Brief (Markdown) ──────────────────────────────────────────────────

def export_country_brief(
    country: str,
    scores: list,
    run_id: str,
) -> Path:
    """Render a country brief in Markdown using the Jinja2 template."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    confirmed = [s for s in scores if not s.human_review_required]
    uncertain = [s for s in scores if s.human_review_required]

    try:
        from jinja2 import Environment, FileSystemLoader

        env      = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH.parent)))
        template = env.get_template(TEMPLATE_PATH.name)

        rendered = template.render(
            country=country,
            run_id=run_id,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            confirmed_scores=confirmed,
            uncertain_scores=uncertain,
            framework="RDTII 2.0",
        )
    except ModuleNotFoundError:
        rendered = _render_country_brief_fallback(country, run_id, confirmed, uncertain)

    out_path = OUTPUT_DIR / f"{country.lower()}_country_brief.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    logger.info(f"[export] Country brief → {out_path}")
    return out_path


def _render_country_brief_fallback(country: str, run_id: str, confirmed: list, uncertain: list) -> str:
    """Minimal Markdown renderer used when Jinja2 is not installed."""
    lines = [
        f"# RDTII Regulatory Analysis: {country.title()}",
        "**Framework:** RDTII 2.0",
        f"**Run ID:** `{run_id}`",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Summary",
        "",
        "| Pillar | Indicator | Score | Confidence | Article | Source Tier |",
        "|--------|-----------|-------|------------|---------|-------------|",
    ]
    for s in confirmed:
        lines.append(
            f"| {s.pillar} | {s.indicator_name} | {s.score:.1f} | {s.confidence} | "
            f"{s.article_ref} | Tier {s.source_tier} |"
        )
    if uncertain:
        lines.append(f"| - | ({len(uncertain)} indicators pending human review) | - | UNCERTAIN | - | - |")

    lines.extend(["", "## Confirmed Scores", ""])
    for s in confirmed:
        lines.extend([
            f"### Indicator {s.indicator_id} - {s.indicator_name}",
            "",
            f"- **Score:** `{s.score:.1f}`",
            f"- **Confidence:** {s.confidence}",
            f"- **Source:** {s.source_title} (Tier {s.source_tier})",
            f"- **Extraction Method:** {s.extraction_method or 'Not recorded'}",
            f"- **Article:** {s.article_ref}",
            f"- **Source URL:** {s.source_url}",
            f"- **Document SHA256:** `{s.sha256[:16]}...`",
            "",
            "**Evidence (verbatim):**",
            f"> \"{s.verbatim_quote}\"",
            "",
            f"**Rationale:** {s.rationale}",
            "",
        ])

    lines.extend([f"## Pending Human Review ({len(uncertain)} items)", ""])
    for s in uncertain:
        lines.extend([
            f"### Indicator {s.indicator_id} - {s.indicator_name}",
            "",
            f"- **Reason:** {s.human_review_reason}",
            f"- **Article checked:** {s.article_ref}",
            f"- **Source:** {s.source_title}",
            f"- **Extraction Method:** {s.extraction_method or 'Not recorded'}",
            "",
        ])
    return "\n".join(lines)
