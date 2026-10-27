"""HTTP bridge called by the Dify Chatflow."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from story_memory.memory import StoryMemory

PROJECT_DIR = Path(__file__).resolve().parents[2]


class RecallRequest(BaseModel):
    user_id: Annotated[str, Field(min_length=1, max_length=256)]
    move: Annotated[str, Field(min_length=1, max_length=2_000)]

    @field_validator("move")
    @classmethod
    def normalize_move(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("剧情指令不能为空")
        return normalized


class RememberRequest(RecallRequest):
    story: Annotated[str, Field(min_length=1, max_length=12_000)]
    turn_id: Annotated[str, Field(min_length=1, max_length=128)]


class ResetRequest(BaseModel):
    user_id: Annotated[str, Field(min_length=1, max_length=256)]


def create_app(memory: StoryMemory | None = None) -> FastAPI:
    data_dir = Path(os.environ.get("STORY_MEMORY_DATA_DIR", PROJECT_DIR / ".data"))
    story_memory = memory or StoryMemory(data_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await story_memory.start()
        try:
            yield
        finally:
            await story_memory.close()

    app = FastAPI(
        title="Outlandish Travel Agency Memory Bridge",
        version="0.1.0",
        description="PowerContext memory used by the Dify story workflow.",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "memory": "PowerContext SQLite"}

    @app.post("/v1/recall")
    async def recall(request: RecallRequest) -> dict[str, Any]:
        result = await story_memory.recall(request.user_id, request.move)
        return {
            "memory_context": result.context,
            "evidence": list(result.evidence),
            "turn_count": result.turn_count,
        }

    @app.post("/v1/remember")
    async def remember(request: RememberRequest) -> dict[str, Any]:
        return await story_memory.remember(
            user_id=request.user_id,
            move=request.move,
            story=request.story,
            turn_id=request.turn_id,
        )

    @app.post("/v1/reset")
    async def reset(request: ResetRequest) -> dict[str, Any]:
        return await story_memory.reset(request.user_id)

    @app.get("/v1/memories")
    async def memories(user_id: str) -> dict[str, Any]:
        if not user_id.strip():
            raise HTTPException(status_code=422, detail="user_id 不能为空")
        return await story_memory.list_memories(user_id)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "story_memory.main:app",
        host=os.environ.get("STORY_MEMORY_HOST", "0.0.0.0"),  # noqa: S104 - Dify runs in a sibling container.
        port=int(os.environ.get("STORY_MEMORY_PORT", "8766")),
    )


if __name__ == "__main__":
    run()
