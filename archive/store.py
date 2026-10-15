"""ChromaDB vector store wrapper. Every hit carries what is needed for a page citation."""
from __future__ import annotations

from dataclasses import dataclass

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


class VectorStore:
    def __init__(self, embedding_function=None):
        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        kwargs = {"embedding_function": embedding_function} if embedding_function else {}
        # Default embedder is Chroma's local MiniLM (no API key). Swap in any
        # chromadb EmbeddingFunction here to change models.
        self._col = self._client.get_or_create_collection(
            config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}, **kwargs
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

        res = self._col.query(query_texts=[query], n_results=k, where=where)
        hits = []
        for text, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append(Hit(
                text=text, score=1.0 - float(dist), doc_id=meta["doc_id"],
                title=meta["title"], course=meta["course"],
                page=int(meta["page"]), chapter=meta.get("chapter", ""),
            ))
        return hits

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
        res = self._col.get(where={"$and": [{"doc_id": doc_id}, {"page": page}]})
        return res["documents"]
