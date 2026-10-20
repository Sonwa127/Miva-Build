"""Pydantic schemas for StitchSmart API request and response models."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


# -----------------------------
# Course Models
# -----------------------------
class CourseCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    code: str = Field(..., min_length=1, max_length=100, examples=["CS 240"])
    name: str = Field(..., min_length=1, max_length=200, examples=["Data Structures & Algorithms"])
    instructor: str = Field("", examples=["Prof. Marcus Vance"])
    term: str = Field("", examples=["Spring 2025"])
    schedule: str = Field("", examples=["MWF 10:00 - 11:15 AM"])
    description: str = Field("", examples=["Asymptotic complexity, balanced search trees (AVL, Red-Black)"])
    credits: float = Field(4.0, examples=[4.0])
    status: str = Field("active", examples=["active"])


class CourseUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    instructor: Optional[str] = None
    term: Optional[str] = None
    schedule: Optional[str] = None
    description: Optional[str] = None
    credits: Optional[float] = None
    status: Optional[str] = None


class CourseResponse(BaseModel):
    id: str
    code: str
    name: str
    instructor: str
    term: str
    schedule: str
    description: str
    credits: float
    status: str
    created_at: str
    stats: Optional[dict[str, Any]] = None


# -----------------------------
# Document Models
# -----------------------------
class DocumentResponse(BaseModel):
    doc_id: str
    sha256: str
    title: str
    course: str
    filename: str
    page_count: int
    chunk_count: int
    ingested_at: str


class PageContentResponse(BaseModel):
    doc_id: str
    page: int
    content: list[str]
    total_pages: int


class ChunkResponse(BaseModel):
    page: int
    index: int
    chapter: str
    text: str


# -----------------------------
# Q&A & Search Models
# -----------------------------
class AskRequest(BaseModel):
    question: str = Field(..., examples=["Can you explain the exact algorithmic difference between recoloring and rotation cases?"])
    course_id: Optional[str] = None
    doc_id: Optional[str] = None
    k: Optional[int] = Field(None, ge=1, le=20)
    provider: Optional[str] = None
    model: Optional[str] = None


class SourceCitation(BaseModel):
    n: int
    citation: str
    title: str
    page: int
    doc_id: str
    text: str


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceCitation]
    related: list[str]
    top_score: float
    llm_called: bool
    low_confidence: bool
    cited: bool
    log_id: Optional[int] = None


class FeedbackRequest(BaseModel):
    query_log_id: int
    rating: int = Field(..., ge=-1, le=1)  # -1 for downvote, 1 for upvote
    comment: str = ""


# -----------------------------
# Flashcard Models
# -----------------------------
class FlashcardGenerateRequest(BaseModel):
    doc_id: str = ""
    course_id: str = ""
    topic: str = ""
    batch_size: int = Field(15, ge=1, le=50)
    difficulty: str = Field("mechanics", examples=["conceptual", "mechanics", "synthesis"])
    include_citations: bool = True


class ReviewRequest(BaseModel):
    card_id: str
    rating: int = Field(..., ge=0, le=5)  # 0=Again, 3=Good, 5=Easy


class FlashcardResponse(BaseModel):
    id: str
    course_id: str
    doc_id: str
    page: int
    question: str
    answer: str
    source_text: str
    difficulty: str
    tags: str
    created_at: str
    ease_factor: float
    interval_days: int
    repetitions: int
    next_review: str
    last_review: Optional[str] = None


class DeckStatsResponse(BaseModel):
    total: int
    new: int
    learning: int
    mature: int
    due_today: int
    retention_rate: float


# -----------------------------
# Quiz Models
# -----------------------------
class QuizGenerateRequest(BaseModel):
    doc_id: str = ""
    course_id: str = ""
    num_questions: int = Field(5, ge=1, le=25)
    topic: str = ""


class QuizQuestionResponse(BaseModel):
    id: str
    quiz_id: str
    question: str
    choices: list[str]
    explanation: Optional[str] = None
    source_page: int


class QuizResponse(BaseModel):
    id: str
    course_id: str
    doc_id: str
    title: str
    question_count: int
    created_at: str
    questions: list[QuizQuestionResponse] = []


class QuizSubmitRequest(BaseModel):
    answers: list[int]  # list of chosen indices (0-3)


class QuizResultResponse(BaseModel):
    attempt_id: str
    quiz_id: str
    score: float
    total: int
    percentage: float
    results: list[dict[str, Any]]
    completed_at: str


# -----------------------------
# Summary & Glossary Models
# -----------------------------
class SummaryGenerateRequest(BaseModel):
    doc_id: str
    course_id: str = ""
    chapter: str = ""
    max_pages: int = Field(15, ge=1, le=50)


class SummaryResponse(BaseModel):
    id: str
    doc_id: str
    course_id: str
    chapter: str
    title: str
    summary_text: str
    key_concepts: list[str]
    source_pages: list[int]
    created_at: str


class GlossaryExtractRequest(BaseModel):
    doc_id: str
    course_id: str = ""
    max_chunks: int = Field(25, ge=5, le=100)


class GlossaryResponse(BaseModel):
    id: str
    course_id: str
    doc_id: str
    term: str
    definition: str
    source_page: int
    related_terms: list[str]
    created_at: str


# -----------------------------
# Evaluation Models
# -----------------------------
class EvaluateRequest(BaseModel):
    question: str = Field(..., examples=["Why does Red-Black tree insertion recoloring not alter black-height?"])
    student_answer: str = Field(..., examples=["Because we turn the parent and uncle black, and the grandparent red..."])
    course_id: str = ""
    doc_id: Optional[str] = None


class EvaluateResponse(BaseModel):
    id: str
    question: str
    student_answer: str
    score: float
    is_ai_generated: bool
    ai_risk_score: float
    feedback: str
    covered_concepts: list[str]
    missing_concepts: list[str]
    citations: list[dict[str, Any]]
    created_at: str


# -----------------------------
# Analytics & Dashboard Models
# -----------------------------
class ActivityItemResponse(BaseModel):
    type: str
    title: str
    detail: str
    course_code: str
    timestamp: str


class DashboardStatsResponse(BaseModel):
    active_courses: int
    time_invested_hours: float
    flashcards_due: int
    documents_indexed: int
    streak_days: int
    recent_activity: list[ActivityItemResponse]
