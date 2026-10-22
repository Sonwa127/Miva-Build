"""FastAPI router for Grounded Q&A and semantic search."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from archive import analytics, qa
from archive.llm import ChatCompletionsLLM, LLMError, get_llm
from archive.store import VectorStore
from ..deps import get_llm_client, get_store
from ..auth import require_admin
from ..models import AskRequest, AskResponse, FeedbackRequest, SourceCitation

router = APIRouter(prefix="/api/qa", tags=["Q&A"])


@router.post("/ask", response_model=AskResponse)
async def ask_assistant(
    payload: AskRequest,
    store: VectorStore = Depends(get_store),
):
    """Ask a question grounded strictly in course materials with page-level citations."""
    try:
        llm = get_llm(payload.provider, payload.model) if payload.provider else get_llm_client()
    except LLMError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    try:
        res = qa.answer_question(
            question=payload.question,
            store=store,
            llm=llm,
            k=payload.k,
            course=payload.course_id,
            doc_id=payload.doc_id,
            previous=payload.previous_question,
        )
    except LLMError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # Log query to telemetry database
    log_id = analytics.log_query(
        question=payload.question,
        answer=res.answer,
        confidence=res.top_score,
        cited=res.cited,
        course=payload.course_id or "",
        doc_id=payload.doc_id or "",
    )

    sources_out = [
        SourceCitation(
            n=s["n"],
            citation=s["citation"],
            title=s["title"],
            page=s["page"],
            doc_id=s["doc_id"],
            text=s["text"],
        )
        for s in res.sources
    ]

    return AskResponse(
        question=res.question,
        answer=res.answer,
        sources=sources_out,
        related=res.related,
        top_score=res.top_score,
        llm_called=res.llm_called,
        low_confidence=res.low_confidence,
        cited=res.cited,
        log_id=log_id,
    )


@router.post("/feedback", status_code=status.HTTP_200_OK)
async def submit_feedback(payload: FeedbackRequest):
    """Submit rating or comment for an AI generated answer."""
    analytics.log_feedback(payload.query_log_id, payload.rating, payload.comment)
    return {"status": "success", "message": "Feedback recorded."}


@router.get("/history", dependencies=[Depends(require_admin)])
async def get_query_history(limit: int = 20):
    """Retrieve recent queries and answers."""
    return analytics.get_low_confidence_queries(threshold=1.0, limit=limit)
