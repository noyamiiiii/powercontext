"""StudyLoop domain and PowerContext integration."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    BuiltinRuntime,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft

SCOPE_IDEMPOTENCY_KEY = "studyloop:personal-study-coach:v1"

SEED_MEMORIES = (
    MemoryEntryInput(
        kind="learning-preference",
        text="学习偏好：每次复习控制在 30 分钟内，先做例题，再用三句话复述概念。",
    ),
    MemoryEntryInput(
        kind="weak-point",
        text="薄弱点：线性代数中矩阵相似与特征值的关系容易混淆，需要先判断可对角化条件。",
    ),
    MemoryEntryInput(
        kind="progress",
        text="历史进度：上一轮已经复习矩阵乘法与行列式，特征向量计算仍需要练习。",
    ),
    MemoryEntryInput(
        kind="outcome",
        text="上次反馈：做矩阵相似例题时在可对角化判断处卡住，闭卷复述仍然漏掉特征向量。",
    ),
)


@dataclass(frozen=True, slots=True)
class MemoryEvidence:
    """One recalled PowerContext entry used by the plan."""

    text: str
    score: float
    matched_by: tuple[str, ...]
    citation: dict[str, str]


@dataclass(frozen=True, slots=True)
class StudyPlan:
    """A plan that exposes the evidence it used."""

    title: str
    duration_minutes: int
    steps: tuple[str, ...]
    evidence: tuple[MemoryEvidence, ...]
    recall_summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "duration_minutes": self.duration_minutes,
            "steps": list(self.steps),
            "evidence": [
                {
                    "text": item.text,
                    "score": round(item.score, 4),
                    "matched_by": list(item.matched_by),
                    "citation": item.citation,
                }
                for item in self.evidence
            ],
            "recall_summary": self.recall_summary,
        }


def build_study_plan(goal: str, minutes: int, evidence: tuple[MemoryEvidence, ...]) -> StudyPlan:
    """Build a deterministic short study session from recalled evidence."""

    normalized_goal = " ".join(goal.split())
    if not normalized_goal:
        raise ValueError("学习目标不能为空")
    if not 10 <= minutes <= 120:
        raise ValueError("学习时长需要在 10 到 120 分钟之间")

    focus = next(
        (item.text for item in evidence if "薄弱点" in item.text or "卡住" in item.text or "漏掉" in item.text),
        None,
    )
    preference = next((item.text for item in evidence if "学习偏好" in item.text), None)
    progress = next((item.text for item in evidence if "进度" in item.text), None)

    review_minutes = max(3, round(minutes * 0.25))
    practice_minutes = max(4, round(minutes * 0.45))
    reflect_minutes = max(3, minutes - review_minutes - practice_minutes)

    steps = [
        f"用 {review_minutes} 分钟回看今天的主题“{normalized_goal}”，只写下已知、未知和要验证的问题。",
        (
            f"用 {practice_minutes} 分钟做针对性练习。优先处理记忆里的薄弱点：{_compact(focus)}"
            if focus
            else f"用 {practice_minutes} 分钟完成两道由易到难的主动练习，并标出卡住的步骤。"
        ),
        (
            f"用 {reflect_minutes} 分钟闭卷复述。按照记忆中的节奏完成：{_compact(preference)}"
            if preference
            else f"用 {reflect_minutes} 分钟闭卷复述概念，再记录一个仍需确认的问题。"
        ),
    ]
    if progress:
        steps.append(f"收尾时核对先前进度：{_compact(progress)}")

    recall_summary = (
        f"已从 PowerContext 召回 {len(evidence)} 条相关学习记忆。"
        if evidence
        else "PowerContext 中没有找到相关历史记忆，本计划不会假装了解你的薄弱点。"
    )
    return StudyPlan(
        title=f"{minutes} 分钟复习计划",
        duration_minutes=minutes,
        steps=tuple(steps),
        evidence=evidence,
        recall_summary=recall_summary,
    )


def _compact(text: str, limit: int = 88) -> str:
    value = " ".join(text.split())
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


class StudyCoach:
    """Single-user embedded PowerContext runtime."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self.database_path = self.data_dir / "powercontext.db"
        self.scheduler_path = self.data_dir / "scheduler.db"
        self._runtime: BuiltinRuntime | None = None
        self._scope_id: str | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def start(self) -> None:
        if self._runtime is not None:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        config = BuiltinConfig(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{self.database_path}"),
        )
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        try:
            self._runtime = await self._exit_stack.enter_async_context(
                open_builtin_runtime(
                    config,
                    scheduler_path=self.scheduler_path,
                ),
            )
        except Exception:
            await self._exit_stack.aclose()
            self._exit_stack = None
            raise

    async def close(self) -> None:
        if self._runtime is None:
            return
        exit_stack = self._exit_stack
        self._runtime = None
        self._scope_id = None
        self._exit_stack = None
        if exit_stack is not None:
            await exit_stack.aclose()

    async def seed_demo(self) -> dict[str, Any]:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope()
        current = await runtime.memory.for_scope(scope_id).list()
        if current.entries:
            return {
                "scope_id": scope_id,
                "seeded": False,
                "memory_entries": len(current.entries),
            }
        result = await runtime.memory.for_scope(scope_id).remember(
            RememberMemoryRequest(entries=SEED_MEMORIES),
        )
        return {
            "scope_id": scope_id,
            "seeded": True,
            "memory_entries": len(SEED_MEMORIES),
            "memory_ref": result.memory_ref.model_dump(mode="json"),
        }

    async def make_plan(self, goal: str, minutes: int) -> StudyPlan:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope()
        query = f"{goal} 薄弱点 学习偏好 历史进度"
        page = await runtime.memory.for_scope(scope_id).search(
            SearchMemoryRequest(query=query, limit=8, mode="fts"),
        )
        evidence = tuple(
            MemoryEvidence(
                text=hit.text,
                score=hit.score,
                matched_by=tuple(str(item) for item in hit.matched_by),
                citation={
                    "artifact_id": hit.memory_ref.artifact_id,
                    "revision": str(hit.memory_ref.revision),
                    "entry_id": hit.entry_id,
                    "entry_version_id": hit.entry_version_id,
                },
            )
            for hit in page.hits
        )
        return build_study_plan(goal, minutes, evidence)

    async def record_outcome(
        self,
        *,
        goal: str,
        reflection: str,
        minutes: int,
        completed: bool,
    ) -> dict[str, Any]:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope()
        text = f"学习记录：目标“{goal}”，计划 {minutes} 分钟，{'已完成' if completed else '未完成'}。复盘：{reflection}"
        result = await runtime.memory.for_scope(scope_id).remember(
            RememberMemoryRequest(
                entries=(MemoryEntryInput(kind="outcome", text=text),),
            ),
        )
        return {
            "status": "remembered",
            "text": text,
            "memory_ref": result.memory_ref.model_dump(mode="json"),
            "entry": None if result.entry is None else result.entry.entry.text,
        }

    async def list_memories(self) -> dict[str, Any]:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope()
        page = await runtime.memory.for_scope(scope_id).list()
        return {
            "scope_id": scope_id,
            "memory_ref": None if page.memory_ref is None else page.memory_ref.model_dump(mode="json"),
            "entries": [
                {
                    "kind": item.entry.kind,
                    "text": item.entry.text,
                    "state": item.state,
                    "citation": item.citation.model_dump(mode="json"),
                }
                for item in page.entries
            ],
        }

    async def _ensure_scope(self) -> str:
        if self._scope_id is not None:
            return self._scope_id
        runtime = self._required_runtime()
        if runtime.scopes is None:
            raise RuntimeError("PowerContext Scope registry is unavailable")
        scope = await runtime.scopes.create(
            ScopeDraft(
                title="StudyLoop personal learning memory",
                summary="Learning preferences, weak points, progress, and session outcomes for one learner.",
                idempotency_key=SCOPE_IDEMPOTENCY_KEY,
            ),
        )
        self._scope_id = scope.scope_id
        return scope.scope_id

    def _required_runtime(self) -> BuiltinRuntime:
        if self._runtime is None:
            raise RuntimeError("StudyCoach has not been started")
        return self._runtime
