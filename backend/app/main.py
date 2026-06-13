"""Trader Terminal API — FastAPI app entrypoint.

Run (from backend/):
    .venv\\Scripts\\uvicorn app.main:app --reload --port 8000

The APScheduler jobs run in-process (ENABLE_SCHEDULER=true). The Next.js
frontend proxies /api/trader-terminal/* here.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import get_settings
from .db import SessionLocal, init_db
from .jobs.scheduler import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("trader-terminal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()

    if settings.demo_seed:
        from .seed.demo_seed import seed_if_empty

        db = SessionLocal()
        try:
            seed_if_empty(db, settings)
        finally:
            db.close()

    scheduler = None
    if settings.enable_scheduler:
        scheduler = build_scheduler()
        scheduler.start()
        log.info("scheduler started with %d jobs (NY time): %s",
                 len(scheduler.get_jobs()),
                 ", ".join(j.id for j in scheduler.get_jobs()))
    else:
        log.info("scheduler disabled (ENABLE_SCHEDULER=false)")

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Trader Terminal API",
    description="Kronos-guided MES research/decision-support terminal. "
                "No broker connection, no order execution.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"ok": True, "service": "trader-terminal-api"}
