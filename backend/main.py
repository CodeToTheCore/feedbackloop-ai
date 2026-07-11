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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import Base, engine
from .routers import requisitions, candidates, interviews

# Creates tables if they don't exist yet. seed.py is what actually populates data.
Base.metadata.create_all(bind=engine)

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

app.include_router(requisitions.router)
app.include_router(candidates.router)
app.include_router(interviews.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "FeedbackLoop AI"}
