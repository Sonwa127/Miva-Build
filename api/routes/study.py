"""FastAPI router for automated study tools: flashcards, quizzes, summaries, and glossary."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from archive import analytics, flashcards, glossary, quizzes, summaries
from archive.llm import ChatCompletionsLLM, LLMError
from archive.store import VectorStore
from ..deps import get_llm_client, get_store
from ..auth import require_admin
from ..models import (
    DeckStatsResponse,
    FlashcardGenerateRequest,
    FlashcardResponse,
    GlossaryExtractRequest,
    GlossaryResponse,
    QuizGenerateRequest,
    QuizQuestionResponse,
    QuizResponse,
    QuizResultResponse,
    QuizSubmitRequest,
    ReviewRequest,
    SummaryGenerateRequest,
    SummaryResponse,
)

router = APIRouter(prefix="/api/study", tags=["Study Tools"])


# ==========================================
# Flashcard Endpoints
# ==========================================
@router.post("/flashcards/generate", response_model=list[FlashcardResponse], dependencies=[Depends(require_admin)])
async def generate_flashcards_endpoint(
    payload: FlashcardGenerateRequest,
    store: VectorStore = Depends(get_store),
    llm: ChatCompletionsLLM = Depends(get_llm_client),
):
    """Generate high-yield active-recall flashcards from document chunks."""
    try:
        cards = flashcards.generate_flashcards(
            doc_id=payload.doc_id,
            store=store,
            llm=llm,
            course_id=payload.course_id,
            topic=payload.topic,
            batch_size=payload.batch_size,
            difficulty=payload.difficulty,
            include_citations=payload.include_citations,
        )
    except LLMError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    analytics.log_activity("flashcard", "Generated Flashcards", f"Created {len(cards)} cards ({payload.difficulty})", payload.course_id)

    return [
        FlashcardResponse(
            id=c.id,
            course_id=c.course_id,
            doc_id=c.doc_id,
            page=c.page,
            question=c.question,
            answer=c.answer,
            source_text=c.source_text,
            difficulty=c.difficulty,
            tags=c.tags,
            created_at=c.created_at,
            ease_factor=c.ease_factor,
            interval_days=c.interval_days,
            repetitions=c.repetitions,
            next_review=c.next_review,
            last_review=c.last_review,
        )
        for c in cards
    ]


@router.get("/flashcards", response_model=list[FlashcardResponse])
async def list_flashcards(
    course_id: str | None = None,
    doc_id: str | None = None,
    due_only: bool = False,
):
    """List flashcards, optionally filtered by course, doc, or review due status."""
    cards = flashcards.get_flashcards(course_id=course_id, doc_id=doc_id, due_only=due_only)
    return [
        FlashcardResponse(
            id=c.id,
            course_id=c.course_id,
            doc_id=c.doc_id,
            page=c.page,
            question=c.question,
            answer=c.answer,
            source_text=c.source_text,
            difficulty=c.difficulty,
            tags=c.tags,
            created_at=c.created_at,
            ease_factor=c.ease_factor,
            interval_days=c.interval_days,
            repetitions=c.repetitions,
            next_review=c.next_review,
            last_review=c.last_review,
        )
        for c in cards
    ]


@router.post("/flashcards/review", response_model=FlashcardResponse, dependencies=[Depends(require_admin)])
async def review_flashcard(payload: ReviewRequest):
    """Submit a rating (0=Again, 3=Good, 5=Easy) to update SM-2 schedule."""
    card = flashcards.review_card(payload.card_id, payload.rating)
    if not card:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found.")

    analytics.log_activity("flashcard", "Reviewed Flashcard", f"Card rating {payload.rating}/5", card.course_id)

    return FlashcardResponse(
        id=card.id,
        course_id=card.course_id,
        doc_id=card.doc_id,
        page=card.page,
        question=card.question,
        answer=card.answer,
        source_text=card.source_text,
        difficulty=card.difficulty,
        tags=card.tags,
        created_at=card.created_at,
        ease_factor=card.ease_factor,
        interval_days=card.interval_days,
        repetitions=card.repetitions,
        next_review=card.next_review,
        last_review=card.last_review,
    )


@router.get("/flashcards/stats", response_model=DeckStatsResponse)
async def get_flashcard_deck_stats(course_id: str | None = None):
    """Retrieve retention rate and review counts."""
    stats = flashcards.get_deck_stats(course_id=course_id)
    return DeckStatsResponse(**stats)


@router.get("/flashcards/export")
async def export_flashcards_anki(course_id: str | None = None):
    """Export cards in tab-separated format for Anki import."""
    tsv_content = flashcards.export_anki(course_id=course_id)
    return Response(
        content=tsv_content,
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": "attachment; filename=flashcards_anki.txt"},
    )


# ==========================================
# Quiz Endpoints
# ==========================================
@router.post("/quizzes/generate", response_model=QuizResponse, dependencies=[Depends(require_admin)])
async def generate_quiz_endpoint(
    payload: QuizGenerateRequest,
    store: VectorStore = Depends(get_store),
    llm: ChatCompletionsLLM = Depends(get_llm_client),
):
    """Generate dynamic multiple-choice quiz grounded in lecture excerpts."""
    try:
        quiz = quizzes.generate_quiz(
            doc_id=payload.doc_id,
            store=store,
            llm=llm,
            course_id=payload.course_id,
            num_questions=payload.num_questions,
            topic=payload.topic,
        )
    except LLMError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    analytics.log_activity("quiz", "Generated Practice Quiz", f"{quiz.title} • {quiz.question_count} questions", payload.course_id)

    return QuizResponse(
        id=quiz.id,
        course_id=quiz.course_id,
        doc_id=quiz.doc_id,
        title=quiz.title,
        question_count=quiz.question_count,
        created_at=quiz.created_at,
        questions=[
            QuizQuestionResponse(
                id=q.id,
                quiz_id=q.quiz_id,
                question=q.question,
                choices=q.choices,
                explanation=q.explanation,
                source_page=q.source_page,
            )
            for q in quiz.questions
        ],
    )


@router.get("/quizzes", response_model=list[QuizResponse])
async def list_quizzes(course_id: str | None = None):
    """List all generated quizzes."""
    items = quizzes.list_quizzes(course_id=course_id)
    return [
        QuizResponse(
            id=q.id,
            course_id=q.course_id,
            doc_id=q.doc_id,
            title=q.title,
            question_count=q.question_count,
            created_at=q.created_at,
            questions=[],
        )
        for q in items
    ]


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse)
async def get_quiz(quiz_id: str):
    """Get full quiz with all questions."""
    q = quizzes.get_quiz(quiz_id)
    if not q:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found.")
    return QuizResponse(
        id=q.id,
        course_id=q.course_id,
        doc_id=q.doc_id,
        title=q.title,
        question_count=q.question_count,
        created_at=q.created_at,
        questions=[
            QuizQuestionResponse(
                id=qq.id,
                quiz_id=qq.quiz_id,
                question=qq.question,
                choices=qq.choices,
                explanation=qq.explanation,
                source_page=qq.source_page,
            )
            for qq in q.questions
        ],
    )


@router.post("/quizzes/{quiz_id}/submit", response_model=QuizResultResponse)
async def submit_quiz(quiz_id: str, payload: QuizSubmitRequest):
    """Submit quiz answers, calculate score, and return explanations."""
    try:
        res = quizzes.submit_quiz(quiz_id, payload.answers)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    analytics.log_activity("quiz", f"Completed Quiz ({res.percentage}%)", f"Score: {int(res.score)}/{res.total}", "")

    return QuizResultResponse(
        attempt_id=res.attempt_id,
        quiz_id=res.quiz_id,
        score=res.score,
        total=res.total,
        percentage=res.percentage,
        results=res.results,
        completed_at=res.completed_at,
    )


@router.get("/quizzes/history/all", dependencies=[Depends(require_admin)])
async def get_quiz_history(course_id: str | None = None):
    """Retrieve quiz attempt history."""
    return quizzes.get_quiz_history(course_id=course_id)


# ==========================================
# Summary Endpoints
# ==========================================
@router.post("/summaries/generate", response_model=SummaryResponse, dependencies=[Depends(require_admin)])
async def generate_summary_endpoint(
    payload: SummaryGenerateRequest,
    store: VectorStore = Depends(get_store),
    llm: ChatCompletionsLLM = Depends(get_llm_client),
):
    """Generate executive summary of a lecture or chapter."""
    try:
        s = summaries.generate_summary(
            doc_id=payload.doc_id,
            store=store,
            llm=llm,
            course_id=payload.course_id,
            chapter=payload.chapter,
            max_pages=payload.max_pages,
        )
    except LLMError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    analytics.log_activity("summary", "Generated Summary", s.title, payload.course_id)

    return SummaryResponse(
        id=s.id,
        doc_id=s.doc_id,
        course_id=s.course_id,
        chapter=s.chapter,
        title=s.title,
        summary_text=s.summary_text,
        key_concepts=s.key_concepts,
        source_pages=s.source_pages,
        created_at=s.created_at,
    )


@router.get("/summaries", response_model=list[SummaryResponse])
async def list_summaries(doc_id: str | None = None, course_id: str | None = None):
    """List generated summaries."""
    items = summaries.get_summaries(doc_id=doc_id, course_id=course_id)
    return [
        SummaryResponse(
            id=s.id,
            doc_id=s.doc_id,
            course_id=s.course_id,
            chapter=s.chapter,
            title=s.title,
            summary_text=s.summary_text,
            key_concepts=s.key_concepts,
            source_pages=s.source_pages,
            created_at=s.created_at,
        )
        for s in items
    ]


# ==========================================
# Glossary Endpoints
# ==========================================
@router.post("/glossary/generate", response_model=list[GlossaryResponse], dependencies=[Depends(require_admin)])
async def extract_glossary_endpoint(
    payload: GlossaryExtractRequest,
    store: VectorStore = Depends(get_store),
    llm: ChatCompletionsLLM = Depends(get_llm_client),
):
    """Auto-extract technical concepts and definitions from a lecture."""
    try:
        entries = glossary.extract_glossary(
            doc_id=payload.doc_id,
            store=store,
            llm=llm,
            course_id=payload.course_id,
            max_chunks=payload.max_chunks,
        )
    except LLMError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    return [
        GlossaryResponse(
            id=g.id,
            course_id=g.course_id,
            doc_id=g.doc_id,
            term=g.term,
            definition=g.definition,
            source_page=g.source_page,
            related_terms=g.related_terms,
            created_at=g.created_at,
        )
        for g in entries
    ]


@router.get("/glossary", response_model=list[GlossaryResponse])
async def get_glossary(course_id: str | None = None, doc_id: str | None = None):
    """Get concept glossary terms."""
    items = glossary.get_glossary(course_id=course_id, doc_id=doc_id)
    return [
        GlossaryResponse(
            id=g.id,
            course_id=g.course_id,
            doc_id=g.doc_id,
            term=g.term,
            definition=g.definition,
            source_page=g.source_page,
            related_terms=g.related_terms,
            created_at=g.created_at,
        )
        for g in items
    ]


@router.get("/glossary/search", response_model=list[GlossaryResponse])
async def search_glossary(q: str, course_id: str | None = None):
    """Search concept glossary terms and definitions."""
    items = glossary.search_glossary(q, course_id=course_id)
    return [
        GlossaryResponse(
            id=g.id,
            course_id=g.course_id,
            doc_id=g.doc_id,
            term=g.term,
            definition=g.definition,
            source_page=g.source_page,
            related_terms=g.related_terms,
            created_at=g.created_at,
        )
        for g in items
    ]
