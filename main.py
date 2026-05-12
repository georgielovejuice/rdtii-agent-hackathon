"""
RDTII Regulatory Intelligence Agent — Main Entry Point
--------------------------------------------------------
Usage:
  python main.py --country thailand --pillars 6 7
  python main.py --country vietnam --pillars 6
  python main.py --country singapore --pillars 6 7 --verbose
"""

from __future__ import annotations
import argparse
import logging
import os
import uuid
from datetime import datetime

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args, **_kwargs):
        return False

try:
    from rich.console import Console
    from rich.table import Table
except ModuleNotFoundError:
    class Console:
        @staticmethod
        def _plain(text):
            return __import__("re").sub(r"\[/?[a-zA-Z0-9_ #=.-]+\]", "", str(text))

        def rule(self, text):
            text = self._plain(text)
            print(f"\n{text}\n" + "-" * min(80, len(str(text))))

        def log(self, text):
            print(self._plain(text))

        def print(self, text=""):
            print(self._plain(text))

    class Table:
        def __init__(self, title="", show_lines=False):
            self.title = title
            self.columns = []
            self.rows = []

        def add_column(self, name, **_kwargs):
            self.columns.append(name)

        def add_row(self, *values):
            self.rows.append(values)

        def __str__(self):
            lines = [self.title, " | ".join(self.columns)]
            lines.append("-" * max(8, len(lines[-1])))
            lines.extend(" | ".join(map(str, row)) for row in self.rows)
            return "\n".join(lines)

from pipeline.discover  import get_seed_sources
from pipeline.extract   import extract_document
from pipeline.authority import resolve_authority, filter_scoreable
from pipeline.retrieval import HybridRetriever
from pipeline.reason    import load_rubric, score_indicator, uncertain_indicator
from pipeline.export    import (
    export_jsonld,
    export_review_queue,
    export_country_brief,
    log_to_audit,
)

load_dotenv()
console = Console()


def run_pipeline(country: str, pillars: list[int], verbose: bool = False):
    run_id  = f"{country}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    log_lvl = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_lvl, format="%(levelname)s [%(name)s] %(message)s")

    console.rule(f"[bold blue]RDTII Agent — {country.title()} | Pillars {pillars}")

    # ── Stage 1: Discover ─────────────────────────────────────────────────────
    console.log("[1/6] Discovering sources...")
    sources = get_seed_sources(country, pillars=pillars)
    log_to_audit(run_id, country, "discover", "seed_sources", f"{len(sources)} sources found")
    console.log(f"  → {len(sources)} sources found")

    if not sources:
        console.print(f"[red]No sources found for '{country}'. Add seed URLs to pipeline/discover.py")
        return

    # ── Stage 2: Extract ──────────────────────────────────────────────────────
    console.log("[2/6] Extracting documents...")
    raw_docs = []
    for source in sources:
        console.log(f"  Extracting: {source.title}")
        doc = extract_document(source)
        raw_docs.append(doc)
        log_to_audit(run_id, country, "extract", source.url,
                     f"{len(doc['articles'])} articles | method={doc.get('extraction_method','?')}")

    # ── Stage 3: Authority Resolution ────────────────────────────────────────
    console.log("[3/6] Resolving authority tiers...")
    resolved  = resolve_authority(raw_docs)
    scoreable = filter_scoreable(resolved)
    log_to_audit(run_id, country, "authority", "resolution",
                 f"{len(scoreable)}/{len(resolved)} docs scoreable")
    console.log(f"  → {len(scoreable)} scoreable docs (Tier 1+2)")

    # ── Stage 4: Build retrieval index ───────────────────────────────────────
    console.log("[4/6] Building hybrid retrieval index...")
    all_articles = [art for doc in scoreable for art in doc.articles]
    if not all_articles:
        console.print("[red]No extractable Tier 1/2 articles found. Cannot score indicators.")
        return
    retriever    = HybridRetriever()
    retriever.build(all_articles, collection_name=f"rdtii_{run_id}")
    retrieval_health = retriever.health()
    log_to_audit(
        run_id,
        country,
        "retrieval",
        f"index_built:{retrieval_health.mode}",
        retrieval_health.summary(),
    )
    console.log(f"  → Retrieval mode: {retrieval_health.mode} ({retrieval_health.summary()})")

    # ── Stage 5: Score each indicator ────────────────────────────────────────
    console.log("[5/6] Scoring RDTII indicators...")
    all_scores = []

    for pillar_num in pillars:
        rubric = load_rubric(pillar_num)
        console.log(f"  Pillar {pillar_num}: {rubric['name']}")

        for indicator in rubric["indicators"]:
            # Get most relevant articles for this indicator
            ctx = retriever.query(indicator)

            best_score = None
            for article in ctx.all_articles:
                # Find which doc this article belongs to (for source metadata)
                source_meta = _find_source_meta(article["id"], scoreable)
                scored = score_indicator(indicator, article, source_meta)

                log_to_audit(run_id, country, "reason",
                             f"{indicator['id']}@{article['section']}",
                             f"score={scored.score} conf={scored.confidence}",
                             "PASS" if scored.confidence != "UNCERTAIN" else "UNCERTAIN")

                # Keep highest-confidence result
                if best_score is None:
                    best_score = scored
                elif _is_better(scored, best_score):
                    best_score = scored

            if best_score:
                all_scores.append(best_score)
                status = f"[green]{best_score.score}[/green]" if not best_score.human_review_required else "[yellow]UNCERTAIN[/yellow]"
                console.log(f"    {indicator['id']} ({indicator['name']}): {status}")
            else:
                fallback = uncertain_indicator(
                    indicator,
                    "No relevant Tier 1/2 article was retrieved for this indicator.",
                )
                all_scores.append(fallback)
                console.log(f"    {indicator['id']} ({indicator['name']}): [yellow]UNCERTAIN[/yellow]")

    # ── Stage 6: Export ───────────────────────────────────────────────────────
    console.log("[6/6] Exporting outputs...")
    jsonld_path = export_jsonld(country, all_scores, run_id)
    brief_path  = export_country_brief(country, all_scores, run_id)
    queue_path  = export_review_queue(country, all_scores, run_id)
    log_to_audit(run_id, country, "export", "complete",
                 f"jsonld={jsonld_path} brief={brief_path} queue={queue_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.rule("[bold green]Pipeline Complete")
    _print_summary(country, all_scores)
    console.print(f"\n[dim]JSON-LD:      {jsonld_path}")
    console.print(f"[dim]Country Brief: {brief_path}")
    if queue_path:
        console.print(f"[dim]Review Queue: {queue_path}")
    console.print(f"[dim]Run ID: {run_id}")
    return all_scores


def _find_source_meta(article_id: str, docs: list) -> dict:
    """Find source metadata for a given article ID."""
    for doc in docs:
        if any(a["id"] == article_id for a in doc.articles):
            return {
                "url": doc.source_url,
                "title": doc.title,
                "tier": doc.tier,
                "extraction_method": doc.extraction_method,
                "effective_date": doc.effective_date,
                "sha256": doc.sha256,
            }
    return {}


def _is_better(new, current) -> bool:
    """Return True if new score is more trustworthy than current."""
    order = {"HIGH": 3, "MEDIUM": 2, "UNCERTAIN": 1}
    if order[new.confidence] > order[current.confidence]:
        return True
    if order[new.confidence] < order[current.confidence]:
        return False
    if new.human_review_required != current.human_review_required:
        return not new.human_review_required
    if new.source_tier < current.source_tier:   # lower tier number = higher authority
        return True
    return False


def _print_summary(country: str, scores: list):
    table = Table(title=f"{country.title()} — RDTII Scores", show_lines=True)
    table.add_column("ID", style="dim")
    table.add_column("Indicator")
    table.add_column("Score", justify="center")
    table.add_column("Conf.", justify="center")
    table.add_column("Tier", justify="center")
    table.add_column("Review?", justify="center")

    for s in scores:
        score_str  = f"{s.score:.1f}" if not s.human_review_required else "—"
        review_str = "YES" if s.human_review_required else "No"
        table.add_row(
            s.indicator_id, s.indicator_name, score_str,
            s.confidence, str(s.source_tier), review_str,
        )

    console.print(table)


def main_cli():
    """Console script entrypoint."""
    parser = argparse.ArgumentParser(description="RDTII Regulatory Intelligence Agent")
    parser.add_argument("--country", required=True, help="Country name (e.g. thailand, vietnam, singapore)")
    parser.add_argument("--pillars", nargs="+", type=int, default=[6, 7], help="Pillar numbers to analyse")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    run_pipeline(
        country=args.country.lower(),
        pillars=args.pillars,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main_cli()
