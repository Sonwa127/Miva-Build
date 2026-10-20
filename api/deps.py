"""Shared dependencies for FastAPI routes."""
from __future__ import annotations

from functools import lru_cache
from typing import Generator

from archive import config
from archive.llm import ChatCompletionsLLM, LLMError, get_llm
from archive.store import VectorStore

_STORE_INSTANCE: VectorStore | None = None


def get_store() -> VectorStore:
    """Return a singleton VectorStore instance."""
    global _STORE_INSTANCE
    if _STORE_INSTANCE is None:
        try:
            _STORE_INSTANCE = VectorStore()
        except Exception as e:
            # If ChromaDB is not yet installed or initialized, log warning
            raise RuntimeError(f"Vector store initialization error: {e}")
    return _STORE_INSTANCE


def get_llm_client() -> ChatCompletionsLLM:
    """Return the configured LLM instance."""
    return get_llm()
