"""Publish weekly course outlines without requiring student accounts."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from archive import courses, course_weeks, registry, resources
from ..auth import require_admin

router = APIRouter(prefix="/api/courses", tags=["Course weeks"])


class WeekInput(BaseModel):
    number: int = Field(..., ge=1, le=52, strict=True)
    title: str = Field("", max_length=200)
    description: str = Field("", max_length=5000)


def find_course(course_id: str):
    course = courses.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found.")
    return course


@router.get("/{course_id}/weeks")
def list_weeks(course_id: str):
    return course_weeks.list_weeks(find_course(course_id).code)


@router.post("/{course_id}/weeks", dependencies=[Depends(require_admin)])
def save_week(course_id: str, payload: WeekInput):
    course = find_course(course_id)
    return course_weeks.save_week(course.code, payload.number, payload.title, payload.description)


@router.delete("/{course_id}/weeks/{number}", status_code=204, dependencies=[Depends(require_admin)])
def delete_week(course_id: str, number: int):
    course = find_course(course_id)
    if registry.list_all(course.code, number) or resources.list_resources(course.code, number):
        raise HTTPException(409, "Move this week's materials to another week or General course materials before removing the week.")
    if not course_weeks.delete_week(course.code, number):
        raise HTTPException(404, "Week not found.")
    return Response(status_code=204)
