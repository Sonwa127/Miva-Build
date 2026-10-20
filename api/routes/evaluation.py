"""FastAPI router for student practice answer evaluation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from archive import analytics, evaluation
from archive.llm import ChatCompletionsLLM, LLMError
from archive.store import VectorStore
from ..deps import get_llm_client, get_store
from ..auth import require_admin
from ..models import EvaluateRequest, EvaluateResponse

router = APIRouter(prefix="/api/evaluation", tags=["Answer Evaluation"])


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_student_answer(
    payload: EvaluateRequest,
    store: VectorStore = Depends(get_store),
    llm: ChatCompletionsLLM = Depends(get_llm_client),
):
    """Semantically evaluate a student practice answer against course materials.
    Scores conceptual understanding, flags AI boilerplate, and highlights missing nuances."""
    try:
        res = evaluation.evaluate_answer(
            question=payload.question,
            student_answer=payload.student_answer,
            store=store,
            llm=llm,
            course_id=payload.course_id,
            doc_id=payload.doc_id,
        )
    except LLMError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    analytics.log_activity("evaluation", f"Answer Evaluated ({int(res.score)}/100)", payload.question[:40], payload.course_id)

    return EvaluateResponse(
        id=res.id,
        question=res.question,
        student_answer=res.student_answer,
        score=res.score,
        is_ai_generated=res.is_ai_generated,
        ai_risk_score=res.ai_risk_score,
        feedback=res.feedback,
        covered_concepts=res.covered_concepts,
        missing_concepts=res.missing_concepts,
        citations=res.citations,
        created_at=res.created_at,
    )


@router.get("/history", dependencies=[Depends(require_admin)])
async def list_evaluations_history(course_id: str | None = None, limit: int = 20):
    """List recent practice answer evaluations."""
    return evaluation.list_evaluations(course_id=course_id, limit=limit)
