"""
Stage 4a — Hybrid Retrieval (ChromaDB + Knowledge Graph)
---------------------------------------------------------
Given a set of article chunks and an RDTII indicator:
  1. ChromaDB semantic search — find top-K most relevant articles
  2. NetworkX Knowledge Graph — follow cross-references between articles
     (e.g. "as defined in Section 3" → retrieve Section 3 too)

This ensures the LLM reasoning stage sees ALL relevant context,
including articles that are only reachable through cross-references.
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

TOP_K = 10   # number of articles to retrieve per indicator query


@dataclass
class RetrievedContext:
    indicator_id: str
    indicator_name: str
    articles: list[dict]            # top-K most relevant article chunks
    cross_refs: list[dict] = field(default_factory=list)   # linked via KG
    all_articles: list[dict] = field(default_factory=list) # articles + cross_refs


class HybridRetriever:
    """
    Hybrid retriever combining ChromaDB (semantic) + NetworkX (graph).
    Call build() once per document set, then query() per indicator.
    """

    def __init__(self):
        self._collection = None
        self._graph      = None
        self._articles   = {}    # id → article dict

    def build(self, articles: list[dict], collection_name: str = "rdtii_docs"):
        """
        Index articles into ChromaDB and build the cross-reference graph.

        Args:
            articles:        List of article dicts from extract.py
            collection_name: ChromaDB collection name (unique per run)
        """
        self._articles = {a["id"]: a for a in articles}
        self._build_vector_index(articles, collection_name)
        self._build_knowledge_graph(articles)
        logger.info(f"[retrieval] Indexed {len(articles)} articles")

    def query(self, indicator: dict) -> RetrievedContext:
        """
        Retrieve the most relevant articles for a given RDTII indicator.
        Combines semantic search results with knowledge graph cross-references.
        """
        query_text = f"{indicator['name']}. {indicator['description']}"

        # Step 1: Semantic retrieval
        top_articles = self._semantic_search(query_text, top_k=TOP_K)

        # Step 2: Keyword boost — re-rank using indicator keywords
        keywords = indicator.get("keywords", [])
        top_articles = _keyword_boost(top_articles, keywords)

        # Step 3: Knowledge graph expansion — follow cross-references
        cross_refs = []
        for article in top_articles:
            linked = self._follow_cross_refs(article["id"])
            cross_refs.extend(linked)

        # Deduplicate
        seen = {a["id"] for a in top_articles}
        unique_cross_refs = [a for a in cross_refs if a["id"] not in seen]

        return RetrievedContext(
            indicator_id=indicator["id"],
            indicator_name=indicator["name"],
            articles=top_articles,
            cross_refs=unique_cross_refs,
            all_articles=top_articles + unique_cross_refs,
        )

    # ── ChromaDB vector index ──────────────────────────────────────────────

    def _build_vector_index(self, articles: list[dict], collection_name: str):
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer

            self._embedder   = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            self._chroma     = chromadb.Client()
            self._collection = self._chroma.get_or_create_collection(collection_name)

            texts = [a.get("text", "")[:1000] for a in articles]   # cap at 1000 chars
            ids   = [a["id"] for a in articles]
            embeddings = self._embedder.encode(texts).tolist()

            self._collection.add(
                documents=texts,
                embeddings=embeddings,
                ids=ids,
                metadatas=[{"section": a.get("section", "")} for a in articles],
            )
            logger.info(f"[retrieval] ChromaDB indexed {len(articles)} articles")
        except Exception as e:
            logger.warning(f"[retrieval] ChromaDB unavailable ({e}) — falling back to keyword search")
            self._collection = None

    def _semantic_search(self, query: str, top_k: int) -> list[dict]:
        if self._collection is None:
            return self._keyword_fallback(query, top_k)

        try:
            query_embedding = self._embedder.encode([query]).tolist()
            results = self._collection.query(
                query_embeddings=query_embedding,
                n_results=min(top_k, len(self._articles)),
            )
            return [self._articles[id_] for id_ in results["ids"][0] if id_ in self._articles]
        except Exception as e:
            logger.warning(f"[retrieval] Semantic search failed ({e}) — keyword fallback")
            return self._keyword_fallback(query, top_k)

    def _keyword_fallback(self, query: str, top_k: int) -> list[dict]:
        """Simple keyword overlap scoring as fallback when ChromaDB is unavailable."""
        query_words = set(query.lower().split())
        scored = []
        for article in self._articles.values():
            text_words = set(article.get("text", "").lower().split())
            overlap    = len(query_words & text_words)
            scored.append((overlap, article))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:top_k]]

    # ── NetworkX Knowledge Graph ───────────────────────────────────────────

    def _build_knowledge_graph(self, articles: list[dict]):
        try:
            import networkx as nx
            self._graph = nx.DiGraph()

            for article in articles:
                self._graph.add_node(article["id"], **article)

            # Find cross-references: "Section X", "Article X", "มาตรา X", etc.
            ref_pattern = re.compile(
                r"\b(?:Section|Article|Điều|มาตรา|Статья|Art\.)\s*(\d+[\w.]*)",
                re.IGNORECASE,
            )
            for article in articles:
                text = article.get("text", "")
                matches = ref_pattern.findall(text)
                for match in matches:
                    target_id = f"section{match.lower().replace('.', '')}"
                    if target_id in self._articles and target_id != article["id"]:
                        self._graph.add_edge(article["id"], target_id, rel="cross_ref")

            logger.info(
                f"[retrieval] Knowledge graph: {self._graph.number_of_nodes()} nodes, "
                f"{self._graph.number_of_edges()} edges"
            )
        except Exception as e:
            logger.warning(f"[retrieval] NetworkX unavailable ({e}) — graph disabled")
            self._graph = None

    def _follow_cross_refs(self, article_id: str, depth: int = 1) -> list[dict]:
        """Follow cross-reference edges from an article up to `depth` hops."""
        if self._graph is None or article_id not in self._graph:
            return []
        linked = []
        try:
            import networkx as nx
            for _, target in nx.bfs_edges(self._graph, article_id, depth_limit=depth):
                if target in self._articles:
                    linked.append(self._articles[target])
        except Exception:
            pass
        return linked


def _keyword_boost(articles: list[dict], keywords: list[str]) -> list[dict]:
    """Re-rank retrieved articles by keyword match count."""
    if not keywords:
        return articles
    kw_lower = [k.lower() for k in keywords]

    def score(article: dict) -> int:
        text = article.get("text", "").lower()
        return sum(1 for kw in kw_lower if kw in text)

    return sorted(articles, key=score, reverse=True)
