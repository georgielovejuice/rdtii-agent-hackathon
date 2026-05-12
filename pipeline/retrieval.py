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
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TOP_K = 10   # number of articles to retrieve per indicator query
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDER_CACHE = None


@dataclass
class RetrievedContext:
    indicator_id: str
    indicator_name: str
    articles: list[dict]            # top-K most relevant article chunks
    cross_refs: list[dict] = field(default_factory=list)   # linked via KG
    all_articles: list[dict] = field(default_factory=list) # articles + cross_refs


@dataclass(frozen=True)
class RetrievalHealth:
    semantic_search: bool
    knowledge_graph: bool
    article_count: int
    graph_edges: int = 0

    @property
    def mode(self) -> str:
        if self.semantic_search and self.knowledge_graph:
            return "semantic+graph"
        if self.semantic_search:
            return "semantic"
        if self.knowledge_graph:
            return "keyword+graph"
        return "keyword"

    def summary(self) -> str:
        graph = f"{self.graph_edges} graph edges" if self.knowledge_graph else "graph disabled"
        semantic = "semantic search active" if self.semantic_search else "keyword fallback active"
        return f"{semantic}; {graph}; {self.article_count} articles"


class HybridRetriever:
    """
    Hybrid retriever combining ChromaDB (semantic) + NetworkX (graph).
    Call build() once per document set, then query() per indicator.
    """

    def __init__(self):
        self._collection = None
        self._graph      = None
        self._articles   = {}    # id → article dict
        self._section_index = {}
        self._embedder   = None

    def build(self, articles: list[dict], collection_name: str = "rdtii_docs"):
        """
        Index articles into ChromaDB and build the cross-reference graph.

        Args:
            articles:        List of article dicts from extract.py
            collection_name: ChromaDB collection name (unique per run)
        """
        self._articles = {}
        self._section_index = {}
        for idx, article in enumerate(articles):
            retrieval_id = f"{article.get('id', 'article')}_{idx}"
            indexed_article = {**article, "_retrieval_id": retrieval_id}
            self._articles[retrieval_id] = indexed_article
            self._section_index.setdefault(article.get("id", ""), []).append(retrieval_id)

        indexed_articles = list(self._articles.values())
        self._build_vector_index(indexed_articles, collection_name)
        self._build_knowledge_graph(indexed_articles)
        logger.info(f"[retrieval] Indexed {len(articles)} articles")

    def health(self) -> RetrievalHealth:
        """Return active retrieval capabilities for logs, UI, and audits."""
        graph_edges = self._graph.number_of_edges() if self._graph is not None else 0
        return RetrievalHealth(
            semantic_search=self._collection is not None,
            knowledge_graph=self._graph is not None,
            article_count=len(self._articles),
            graph_edges=graph_edges,
        )

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
            linked = self._follow_cross_refs(article["_retrieval_id"])
            cross_refs.extend(linked)

        # Deduplicate
        seen = {a["_retrieval_id"] for a in top_articles}
        unique_cross_refs = [a for a in cross_refs if a["_retrieval_id"] not in seen]

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

            self._embedder   = _get_embedder()
            self._chroma     = chromadb.Client()
            self._collection = self._chroma.get_or_create_collection(collection_name)

            texts = [a.get("text", "")[:1000] for a in articles]   # cap at 1000 chars
            ids   = [a["_retrieval_id"] for a in articles]
            embeddings = self._embedder.encode(texts, show_progress_bar=False).tolist()

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
            query_embedding = self._embedder.encode([query], show_progress_bar=False).tolist()
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
                self._graph.add_node(article["_retrieval_id"], **article)

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
                    for target_retrieval_id in self._section_index.get(target_id, []):
                        if target_retrieval_id != article["_retrieval_id"]:
                            self._graph.add_edge(
                                article["_retrieval_id"],
                                target_retrieval_id,
                                rel="cross_ref",
                            )

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


def _get_embedder():
    """Load the multilingual embedding model once per process."""
    global _EMBEDDER_CACHE
    if _EMBEDDER_CACHE is None:
        from sentence_transformers import SentenceTransformer
        _EMBEDDER_CACHE = SentenceTransformer(
            EMBEDDING_MODEL,
            local_files_only=not _allow_embedding_download(),
        )
    return _EMBEDDER_CACHE


def _allow_embedding_download() -> bool:
    """Allow online model downloads only when explicitly requested."""
    return os.getenv("RDTII_ALLOW_EMBEDDING_DOWNLOAD", "").lower() in {"1", "true", "yes"}
