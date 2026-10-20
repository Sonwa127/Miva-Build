"""FastAPI router for analytics telemetry and curriculum pain points."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from ..auth import require_admin

from archive import analytics, courses, flashcards, registry
from ..models import ActivityItemResponse, DashboardStatsResponse

router = APIRouter(prefix="/api/analytics", tags=["Analytics"], dependencies=[Depends(require_admin)])


@router.get("/dashboard", response_model=DashboardStatsResponse)
async def get_dashboard_summary():
    """Aggregate high-level telemetry for the Home Dashboard."""
    # Active courses
    all_courses = courses.list_courses(status="active")
    # Ingested docs
    all_docs = registry.list_all()
    # Flashcard stats
    fc_stats = flashcards.get_deck_stats()
    # Study telemetry
    study_stats = analytics.get_study_stats()
    # Activities
    raw_activities = analytics.get_activity_feed(limit=6)

    activity_items = [
        ActivityItemResponse(
            type=a["type"],
            title=a["title"],
            detail=a["detail"],
            course_code=a.get("course_code", ""),
            timestamp=a.get("timestamp", ""),
        )
        for a in raw_activities
    ]

    return DashboardStatsResponse(
        active_courses=len(all_courses),
        time_invested_hours=float(study_stats.get("study_hours", 0.0)),
        flashcards_due=int(fc_stats.get("due_today", 0)),
        documents_indexed=len(all_docs),
        streak_days=int(study_stats.get("streak_days", 0)),
        recent_activity=activity_items,
    )


@router.get("/weak-areas")
async def get_curriculum_weak_areas(threshold: float = 0.50, limit: int = 20):
    """List low-confidence or downvoted student queries to identify curricular gaps."""
    return analytics.get_low_confidence_queries(threshold=threshold, limit=limit)


@router.get("/topics")
async def get_frequent_topics(course: str | None = None, limit: int = 15):
    """Get most frequently searched lecture topics."""
    return analytics.get_frequent_topics(course=course, limit=limit)


@router.get("/activity", response_model=list[ActivityItemResponse])
async def get_recent_activity(limit: int = 10):
    """List recent activity events across Q&A, quizzes, and flashcards."""
    items = analytics.get_activity_feed(limit=limit)
    return [
        ActivityItemResponse(
            type=a["type"],
            title=a["title"],
            detail=a["detail"],
            course_code=a.get("course_code", ""),
            timestamp=a.get("timestamp", ""),
        )
        for a in items
    ]
