"""ChromaDB vector store wrapper. Every hit carries what is needed for a page citation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
import unicodedata
from typing import Any

import chromadb

from . import config
from .chunker import Chunk


@dataclass
class Hit:
    text: str
    score: float         # cosine similarity, higher is better (0..1 for normal text)
    doc_id: str
    title: str
    course: str
    page: int
    chapter: str

    @property
    def citation(self) -> str:
        return f"[{self.title}, p. {self.page}]"


from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class FastOfflineEmbedding(EmbeddingFunction):
    """Deterministic, zero-download lexical embedding for offline search.

    Words, adjacent word pairs, and character trigrams make retrieval tolerant of
    punctuation and light inflection while remaining fully local.
    """
    def __init__(self, dim: int = 384):
        self.dim = dim

    @staticmethod
    def tokenize(text: str) -> list[str]:
        normalized = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
        words = re.findall(r"[^\W_]+(?:'[^\W_]+)?", normalized, flags=re.UNICODE)
        return [w[:-2] if w.endswith("'s") else w for w in words]

    @classmethod
    def _features(cls, text: str) -> list[tuple[str, float]]:
        words = cls.tokenize(text)
        features: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words if len(w) > 1]
        features.extend((f"b:{a}_{b}", 1.35) for a, b in zip(words, words[1:]))
        for word in words:
            compact = f"^{word}$"
            if len(word) >= 4:
                features.extend((f"c:{compact[i:i + 3]}", 0.25) for i in range(len(compact) - 2))
        return features

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feature, weight in self._features(text):
            h = int(hashlib.md5(feature.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            vec[idx] += weight
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed_one(t) for t in input]

    @staticmethod
    def name() -> str:
        return "stitchsmart-fast-offline-v2"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "FastOfflineEmbedding":
        return FastOfflineEmbedding(dim=int(config.get("dim", 384)))

    def get_config(self) -> dict[str, Any]:
        return {"dim": self.dim}


_SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "define", "describe",
    "explain", "for", "from", "how", "in", "is", "it", "of", "on", "or",
    "state", "tell", "the", "to", "was", "what", "when", "where", "which",
    "who", "why", "with",
}


class VectorStore:
    def __init__(self, embedding_function=None):
        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        # Use FastOfflineEmbedding by default to prevent slow external ONNX downloads during offline use
        ef = embedding_function or FastOfflineEmbedding()
        # Never delete a collection because initialization failed: the registry and
        # vector index would silently diverge. Versioned collection names handle
        # intentional embedding migrations safely.
        self._col = self._client.get_or_create_collection(
            config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine", "index_version": "2"},
            embedding_function=ef,
        )

    def add_chunks(self, doc_id: str, title: str, course: str, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        batch = 128
        for i in range(0, len(chunks), batch):
            part = chunks[i:i + batch]
            self._col.upsert(
                ids=[f"{doc_id}:{c.page}:{c.index}" for c in part],
                documents=[c.text for c in part],
                metadatas=[{
                    "doc_id": doc_id, "title": title, "course": course,
                    "page": c.page, "chapter": c.chapter,
                } for c in part],
            )

    def delete_doc(self, doc_id: str) -> None:
        self._col.delete(where={"doc_id": doc_id})

    def count(self) -> int:
        return self._col.count()

    def count_doc(self, doc_id: str) -> int:
        """Count the stored chunks for one document."""
        return len(self._col.get(where={"doc_id": doc_id}, include=[])["ids"])

    def search(self, query: str, k: int = 5, course: str | None = None,
               doc_id: str | None = None) -> list[Hit]:
        where = None
        filters = []
        if course:
            filters.append({"course": course})
        if doc_id:
            filters.append({"doc_id": doc_id})
        if len(filters) == 1:
            where = filters[0]
        elif filters:
            where = {"$and": filters}

        # Pull a wider semantic candidate set, then add exact-term coverage. Pure
        # cosine similarity tends to underrate long lecture chunks even when all
        # of the student's key terms occur verbatim.
        candidate_count = min(max(k * 6, 24), max(self._col.count(), 1))
        res = self._col.query(query_texts=[query], n_results=candidate_count, where=where)
        query_words = [
            w for w in FastOfflineEmbedding.tokenize(query)
            if len(w) > 1 and w not in _SEARCH_STOPWORDS
        ]
        query_terms = set(query_words)
        query_pairs = set(zip(query_words, query_words[1:]))
        hits = []
        for text, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            semantic_score = max(0.0, 1.0 - float(dist))
            document_words = FastOfflineEmbedding.tokenize(text)
            document_terms = set(document_words)
            term_coverage = (
                len(query_terms & document_terms) / len(query_terms)
                if query_terms else 0.0
            )
            document_pairs = set(zip(document_words, document_words[1:]))
            pair_coverage = (
                len(query_pairs & document_pairs) / len(query_pairs)
                if query_pairs else 0.0
            )
            lexical_score = (0.85 * term_coverage) + (0.15 * pair_coverage)
            combined_score = (0.90 * lexical_score) + (0.10 * semantic_score)
            hits.append(Hit(
                text=text, score=combined_score, doc_id=meta["doc_id"],
                title=meta["title"], course=meta["course"],
                page=int(meta["page"]), chapter=meta.get("chapter", ""),
            ))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:k]

    def list_chunks(self, doc_id: str, page: int | None = None) -> list[tuple[int, int, str, str]]:
        """Return (page, index, chapter, text) rows for a document, in reading order."""
        where = {"doc_id": doc_id} if page is None else {"$and": [{"doc_id": doc_id}, {"page": page}]}
        res = self._col.get(where=where, include=["documents", "metadatas"])
        rows = []
        for cid, text, meta in zip(res["ids"], res["documents"], res["metadatas"]):
            rows.append((int(meta["page"]), int(cid.rsplit(":", 1)[1]), meta.get("chapter", ""), text))
        rows.sort(key=lambda r: (r[0], r[1]))
        return rows

    def get_page(self, doc_id: str, page: int) -> list[str]:
        """All chunk texts for one page, in order. Useful for summaries and flashcards later."""
        return [row[3] for row in self.list_chunks(doc_id, page)]
