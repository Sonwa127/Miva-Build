"""FastAPI router for courses management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from archive import courses, course_weeks, registry, resources
from ..models import CourseCreate, CourseResponse, CourseUpdate
from ..auth import require_admin

router = APIRouter(prefix="/api/courses", tags=["Courses"])


@router.get("", response_model=list[CourseResponse])
async def list_courses(status: str | None = None):
    """List all courses, optionally filtered by status ('active', 'completed')."""
    records = courses.list_courses(status=status)
    out = []
    for c in records:
        stats = courses.get_course_stats(c.id)
        out.append(CourseResponse(
            id=c.id,
            code=c.code,
            name=c.name,
            instructor=c.instructor,
            term=c.term,
            schedule=c.schedule,
            description=c.description,
            credits=c.credits,
            status=c.status,
            created_at=c.created_at,
            stats=stats,
        ))
    return out


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_course(payload: CourseCreate):
    """Create a new course."""
    existing = courses.get_course(payload.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Course with code '{payload.code}' already exists.",
        )
    c = courses.create_course(
        code=payload.code,
        name=payload.name,
        instructor=payload.instructor,
        term=payload.term,
        schedule=payload.schedule,
        description=payload.description,
        credits=payload.credits,
        status=payload.status,
    )
    return CourseResponse(
        id=c.id,
        code=c.code,
        name=c.name,
        instructor=c.instructor,
        term=c.term,
        schedule=c.schedule,
        description=c.description,
        credits=c.credits,
        status=c.status,
        created_at=c.created_at,
        stats={"doc_count": 0, "page_count": 0, "chunk_count": 0, "flashcard_count": 0, "quiz_count": 0},
    )


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(course_id: str):
    """Retrieve course details and statistics."""
    c = courses.get_course(course_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
    stats = courses.get_course_stats(c.id)
    return CourseResponse(
        id=c.id,
        code=c.code,
        name=c.name,
        instructor=c.instructor,
        term=c.term,
        schedule=c.schedule,
        description=c.description,
        credits=c.credits,
        status=c.status,
        created_at=c.created_at,
        stats=stats,
    )


@router.put("/{course_id}", response_model=CourseResponse, dependencies=[Depends(require_admin)])
async def update_course(course_id: str, payload: CourseUpdate):
    """Update course attributes."""
    fields = payload.model_dump(exclude_unset=True)
    existing = courses.get_course(course_id)
    if not existing:
        raise HTTPException(404, "Course not found.")
    if "code" in fields and fields["code"] != existing.code:
        raise HTTPException(422, "Course codes cannot be changed after creation. Edit the name or description instead.")
    if any(value is None for value in fields.values()):
        raise HTTPException(422, "Course fields cannot be null.")
    if "name" in fields and not fields["name"].strip():
        raise HTTPException(422, "Course name cannot be blank.")
    updated = courses.update_course(course_id, **fields)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
    stats = courses.get_course_stats(updated.id)
    return CourseResponse(
        id=updated.id,
        code=updated.code,
        name=updated.name,
        instructor=updated.instructor,
        term=updated.term,
        schedule=updated.schedule,
        description=updated.description,
        credits=updated.credits,
        status=updated.status,
        created_at=updated.created_at,
        stats=stats,
    )


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_course(course_id: str):
    """Delete a course."""
    existing = courses.get_course(course_id)
    if existing and (registry.list_all(existing.code) or resources.list_resources(existing.code) or course_weeks.list_weeks(existing.code)):
        raise HTTPException(409, "Remove this course's PDFs, videos, links, and weeks before deleting it.")
    ok = courses.delete_course(course_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
    return None
