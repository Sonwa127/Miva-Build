"""Public resource browsing with administrator-only publishing."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from archive import courses, course_weeks, resources
from ..auth import require_admin

router = APIRouter(prefix="/api/resources", tags=["Resources"])


class ResourceInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=5000)
    course: str = Field("", max_length=100)
    kind: Literal["video", "youtube", "youtube_playlist", "vimeo", "vimeo_showcase", "loom", "dailymotion", "dailymotion_playlist", "video_file", "link"] = "video"
    url: str = Field(..., max_length=2048)
    week: int | None = Field(None, ge=0, le=52, strict=True)


@router.get("")
def list_resources(course: str | None = None, week: int | None = Query(None, ge=0, le=52)):
    return resources.list_resources(course, week)


def save(payload: ResourceInput, resource_id: str | None = None):
    if not payload.title.strip():
        raise HTTPException(422, "A title is required.")
    course = courses.get_course(payload.course) if payload.course else None
    if payload.course and not course:
        raise HTTPException(422, "Select an existing course, or General resources.")
    course_code = course.code if course else ""
    existing = resources.get_resource(resource_id) if resource_id else None
    week = payload.week
    if week is None:
        week = existing["week"] if existing and existing["course"] == course_code else 0
    try:
        course_weeks.validate_placement(course_code, week)
        return resources.save_resource(payload.title, payload.description, course_code, payload.kind, payload.url, resource_id, week)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
def create_resource(payload: ResourceInput):
    return save(payload)


@router.put("/{resource_id}", dependencies=[Depends(require_admin)])
def update_resource(resource_id: str, payload: ResourceInput):
    if not resources.get_resource(resource_id):
        raise HTTPException(404, "Resource not found.")
    return save(payload, resource_id)


@router.delete("/{resource_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_resource(resource_id: str):
    if not resources.delete_resource(resource_id):
        raise HTTPException(404, "Resource not found.")
    return Response(status_code=204)
