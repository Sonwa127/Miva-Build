"""FastAPI application factory, page template routing, and static file mounting."""
from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from archive import courses, registry, resources, summaries, glossary
from archive.llm import LLMError
from .routes import analytics, courses as courses_router, documents, evaluation, qa, study
from .routes import admin, resources as resources_router
from .auth import can_setup_locally, is_admin, load_credentials

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
TEMPLATES_DIR = FRONTEND_DIR / "templates"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="StitchSmart Study Archive",
    description="Intelligent course material archive, citation-grounded RAG, automated study tools & analytics.",
    version="1.0.0",
)

# CORS setup
# Browser clients use the same origin; administrator cookies are never shared
# with arbitrary cross-origin websites.

# Static and Templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API Routers
app.include_router(courses_router.router)
app.include_router(documents.router)
app.include_router(qa.router)
app.include_router(study.router)
app.include_router(analytics.router)
app.include_router(evaluation.router)
app.include_router(admin.router)
app.include_router(resources_router.router)


@app.middleware("http")
async def page_security(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith(("/admin", "/api/admin")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
    return response


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": str(exc)},
    )




# ==========================================
# Web Page Routes (Jinja2 HTML rendering)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def home_dashboard_page(request: Request):
    """Render the Home Dashboard screen."""
    return templates.TemplateResponse(request=request, name="public_home.html", context={
        "active_page": "home", "courses": courses.list_courses(),
        "documents": registry.list_all(), "resources": resources.list_resources(),
    })


@app.get("/courses", response_class=HTMLResponse)
async def courses_library_page(request: Request):
    """Render the Course Library screen."""
    return templates.TemplateResponse(request=request, name="public_courses.html", context={
        "active_page": "courses", "courses": courses.list_courses(),
    })


@app.get("/courses/{course_id}", response_class=HTMLResponse)
async def course_overview_page(request: Request, course_id: str):
    """Render the Course Overview screen for a specific course."""
    c = courses.get_course(course_id)
    if not c:
        raise HTTPException(status_code=404, detail="Course not found.")
    return templates.TemplateResponse(
        request=request,
        name="public_course_detail.html",
        context={"course": c, "active_page": "courses", "documents": registry.list_all(c.code),
                 "resources": resources.list_resources(c.code),
                 "summaries": summaries.get_summaries(course_id=c.code),
                 "glossary": glossary.get_glossary(course_id=c.code)},
    )


@app.get("/viewer/{doc_id}", response_class=HTMLResponse)
async def pdf_viewer_page(request: Request, doc_id: str, page: int = 1):
    """Render the Split PDF / Slide Reading Pane screen."""
    document = registry.get(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    initial_page = min(max(page, 1), max(document.page_count, 1))
    return templates.TemplateResponse(
        request=request,
        name="original_pdf.html",
        context={
            "doc_id": doc_id,
            "document": document,
            "initial_page": initial_page,
            "active_page": "viewer",
        },
    )


@app.get("/ask", response_class=HTMLResponse)
async def ask_ai_page(request: Request, course_id: str = ""):
    """Render the Grounded AI Q&A Assistant screen."""
    all_courses = courses.list_courses()
    return templates.TemplateResponse(
        request=request,
        name="ask_ai.html",
        context={"courses": all_courses, "selected_course": course_id, "active_page": "ask"},
    )


@app.get("/study", response_class=HTMLResponse)
async def study_hub_page(request: Request, course_id: str = ""):
    """Render the Flashcards & Dynamic Quizzes Hub screen."""
    all_courses = courses.list_courses()
    return templates.TemplateResponse(
        request=request,
        name="study.html",
        context={"courses": all_courses, "selected_course": course_id, "active_page": "study", "is_admin": is_admin(request)},
    )


@app.get("/resources", response_class=HTMLResponse)
async def resource_library_page(request: Request, course: str = "", kind: str = "", q: str = ""):
    items = resources.list_resources(course or None)
    documents_list = registry.list_all(course or None) if kind in {"", "pdf"} else []
    if kind == "video":
        items = [item for item in items if item["is_video"]]
    elif kind == "playlist":
        items = [item for item in items if item["is_playlist"]]
    elif kind:
        items = [item for item in items if item["kind"] == kind]
    if q.strip():
        query = q.strip().casefold()
        items = [item for item in items if query in f"{item['title']} {item['description']} {item['course']}".casefold()]
        documents_list = [doc for doc in documents_list if query in f"{doc.title} {doc.filename} {doc.course}".casefold()]
    return templates.TemplateResponse(request=request, name="resources.html", context={
        "active_page": "resources", "resources": items, "documents": documents_list,
        "courses": courses.list_courses(), "selected_course": course, "selected_kind": kind, "query": q,
    })


@app.get("/watch/{resource_id}", response_class=HTMLResponse)
async def watch_resource(request: Request, resource_id: str):
    resource = resources.get_resource(resource_id)
    if not resource or not resource["is_video"]:
        raise HTTPException(404, "Video not found.")
    return templates.TemplateResponse(request=request, name="watch.html", context={
        "active_page": "resources", "resource": resource,
    })


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request=request, name="admin_login.html", context={
        "active_page": "admin", "configured": bool(load_credentials()),
        "can_setup_locally": can_setup_locally(request),
    })


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request=request, name="admin.html", context={
        "active_page": "admin", "courses": courses.list_courses(),
        "documents": registry.list_all(), "resources": resources.list_resources(),
    })
