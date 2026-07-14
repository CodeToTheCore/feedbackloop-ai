"""
main.py
-------
FastAPI application entrypoint.

Run locally with:
    uvicorn backend.main:app --reload

Then open:
    http://127.0.0.1:8000            -> frontend dashboard
    http://127.0.0.1:8000/docs       -> interactive API docs (auto-generated)
"""

from pathlib import Path

# Load .env before anything reads os.getenv (DATABASE_URL, ANTHROPIC_API_KEY, ...).
# Safe no-op if python-dotenv isn't installed or there's no .env file.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .database import Base, engine
from .routers import requisitions, candidates, interviews

# Creates tables if they don't exist yet. seed.py is what actually populates data.
Base.metadata.create_all(bind=engine)

from .database import Base, engine, SessionLocal
from . import models

Base.metadata.create_all(bind=engine)

# Auto-seed if the database is empty -- makes the app self-healing on
# platforms like Render's free tier where local disk doesn't persist
# across restarts.
def _seed_if_empty():
    db = SessionLocal()
    try:
        if db.query(models.Requisition).count() == 0:
            from . import seed
            seed.run()
    finally:
        db.close()

_seed_if_empty()

app = FastAPI(
    title="FeedbackLoop AI",
    description="Interview feedback & ranking agent -- backend API, built from the PRD in FeedbackLoop_AI_Agent_PRD.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # fine for local/class-demo use; tighten before any real deploy
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(SQLAlchemyError)
async def db_error_handler(request: Request, exc: SQLAlchemyError):
    """
    Any database-layer failure (connection loss, query error, etc.) is turned
    into a single clean message instead of leaking a 500 / stack trace to the
    client. HTTPExceptions (e.g. 404 "not found") are unaffected -- they keep
    their own detail. Matches the Eval Card's DB-error case.
    """
    return JSONResponse(
        status_code=503,
        content={"detail": "System error! Please refresh and try again"},
    )


app.include_router(requisitions.router)
app.include_router(candidates.router)
app.include_router(interviews.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/intro")
def serve_intro():
    """Animated cold-open title card -- handy as a presentation opener at /intro."""
    return FileResponse(FRONTEND_DIR.parent / "intro.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "FeedbackLoop AI"}
