"""StudyLoop HTTP application and functional web interface."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from studyloop.coach import StudyCoach

PROJECT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_DIR / "frontend"


class PlanRequest(BaseModel):
    goal: Annotated[str, Field(min_length=1, max_length=500)]
    minutes: Annotated[int, Field(ge=10, le=120)] = 30

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("学习目标不能为空")
        return normalized


class OutcomeRequest(PlanRequest):
    reflection: Annotated[str, Field(min_length=1, max_length=2_000)]
    completed: bool = True

    @field_validator("reflection")
    @classmethod
    def normalize_reflection(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("复盘内容不能为空")
        return normalized


def create_app(coach: StudyCoach | None = None) -> FastAPI:
    data_dir = Path(os.environ.get("STUDYLOOP_DATA_DIR", PROJECT_DIR / ".data"))
    active_coach = coach or StudyCoach(data_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await active_coach.start()
        await active_coach.seed_demo()
        try:
            yield
        finally:
            await active_coach.close()

    app = FastAPI(
        title="StudyLoop",
        version="0.1.0",
        description="A study coach whose memory persists through PowerContext.",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "memory": "PowerContext SQLite"}

    @app.get("/api/memories")
    async def memories() -> dict[str, Any]:
        return await active_coach.list_memories()

    @app.post("/api/seed")
    async def seed() -> dict[str, Any]:
        return await active_coach.seed_demo()

    @app.post("/api/plan")
    async def plan(request: PlanRequest) -> dict[str, Any]:
        try:
            return (await active_coach.make_plan(request.goal, request.minutes)).as_dict()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/outcomes")
    async def outcome(request: OutcomeRequest) -> dict[str, Any]:
        return await active_coach.record_outcome(
            goal=request.goal,
            minutes=request.minutes,
            reflection=request.reflection,
            completed=request.completed,
        )

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/app/")

    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="app")
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "studyloop.main:app",
        host=os.environ.get("STUDYLOOP_HOST", "127.0.0.1"),
        port=int(os.environ.get("STUDYLOOP_PORT", "8000")),
    )


if __name__ == "__main__":
    run()
