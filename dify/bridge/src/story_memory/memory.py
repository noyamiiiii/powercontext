"""PowerContext-backed story memory for the Outlandish Travel Agency."""

from __future__ import annotations

import hashlib
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

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

SEED_MEMORIES = (
    MemoryEntryInput(
        kind="world-setting",
        text=(
            "世界设定：离谱旅行社只在午夜后营业。向导阿拐是一架会说话的纸飞机，"
            "负责把旅客送进世界上最不合常理的事件现场。"
        ),
    ),
    MemoryEntryInput(
        kind="character",
        text=("角色设定：阿拐礼貌、认真，把离谱事件当作普通公务处理。它信任玩家的每个选择，但会提醒每个选择留下后果。"),
    ),
    MemoryEntryInput(
        kind="game-rule",
        text=(
            "游戏规则：输入任何行动、台词或脑洞都会推动剧情。"
            "输出保持轻松、有趣、适龄，不生成血腥、色情或针对现实人物的伤害内容。"
        ),
    ),
    MemoryEntryInput(
        kind="start",
        text="开始方式：输入 START 或直接说出一个离谱行动，故事会从当前地点继续。",
    ),
)


@dataclass(frozen=True, slots=True)
class RecallResult:
    context: str
    evidence: tuple[dict[str, Any], ...]
    turn_count: int


def _user_key(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


class StoryMemory:
    """One embedded PowerContext Runtime with one isolated Scope per Dify user."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self._runtime: BuiltinRuntime | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._scope_cache: dict[str, str] = {}

    async def start(self) -> None:
        if self._runtime is not None:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        config = BuiltinConfig(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{self.data_dir / 'story-memory.db'}"),
        )
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        try:
            self._runtime = await self._exit_stack.enter_async_context(
                open_builtin_runtime(
                    config,
                    scheduler_path=self.data_dir / "scheduler.db",
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
        self._exit_stack = None
        self._scope_cache.clear()
        if exit_stack is not None:
            await exit_stack.aclose()

    async def recall(self, user_id: str, move: str) -> RecallResult:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope(user_id)
        await self._seed_if_empty(scope_id)
        memory = runtime.memory.for_scope(scope_id)
        entries = await memory.list()
        records_by_version = {record.entry.entry_version_id: record for record in entries.entries}
        reset_revision = max(
            (record.entry.created_in_revision for record in entries.entries if record.entry.kind == "story-reset"),
            default=0,
        )
        query = f"{move} 剧情 角色 地点 当前状态 玩家选择"
        page = await memory.search(SearchMemoryRequest(query=query, limit=10, mode="fts"))
        hits = [
            hit
            for hit in page.hits
            if hit.entry_version_id in records_by_version
            and records_by_version[hit.entry_version_id].entry.created_in_revision >= reset_revision
        ]

        evidence_items: list[dict[str, Any]] = []
        seen_versions: set[str] = set()
        for record in entries.entries:
            if record.state != "active" or record.entry.kind not in {"world-setting", "character", "game-rule"}:
                continue
            seen_versions.add(record.entry.entry_version_id)
            evidence_items.append(
                self._evidence(
                    record.entry.text,
                    0.0,
                    (),
                    record.citation.model_dump(mode="json"),
                ),
            )

        for hit in hits:
            if hit.entry_version_id in seen_versions:
                continue
            seen_versions.add(hit.entry_version_id)
            record = records_by_version[hit.entry_version_id]
            evidence_items.append(
                self._evidence(
                    hit.text,
                    hit.score,
                    tuple(str(item) for item in hit.matched_by),
                    record.citation.model_dump(mode="json"),
                ),
            )

        recent_state = sorted(
            (
                record
                for record in entries.entries
                if record.state == "active"
                and record.entry.kind in {"player-choice", "story-scene"}
                and record.entry.created_in_revision >= reset_revision
            ),
            key=lambda record: record.entry.created_in_revision,
        )[-4:]
        for record in recent_state:
            if record.entry.entry_version_id in seen_versions:
                continue
            seen_versions.add(record.entry.entry_version_id)
            evidence_items.append(
                self._evidence(
                    record.entry.text,
                    0.0,
                    (),
                    record.citation.model_dump(mode="json"),
                ),
            )

        if len(hits) == 0:
            fallback = sorted(
                (
                    record
                    for record in entries.entries
                    if record.state == "active" and record.entry.created_in_revision >= reset_revision
                ),
                key=lambda record: record.entry.created_in_revision,
            )[-6:]
            for record in fallback:
                if record.entry.entry_version_id in seen_versions:
                    continue
                seen_versions.add(record.entry.entry_version_id)
                evidence_items.append(
                    self._evidence(
                        record.entry.text,
                        0.0,
                        (),
                        record.citation.model_dump(mode="json"),
                    ),
                )

        evidence = tuple(evidence_items)
        context = "\n".join(f"- {item['text']}" for item in evidence) or "暂无相关记忆。"
        turn_count = sum(
            1
            for record in entries.entries
            if record.entry.kind == "player-choice" and record.entry.created_in_revision >= reset_revision
        )
        return RecallResult(context=context, evidence=evidence, turn_count=turn_count)

    async def remember(
        self,
        *,
        user_id: str,
        move: str,
        story: str,
        turn_id: str,
    ) -> dict[str, Any]:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope(user_id)
        await self._seed_if_empty(scope_id)
        memory = runtime.memory.for_scope(scope_id)
        entries = await memory.list()
        latest_reset = max(
            (record for record in entries.entries if record.entry.kind == "story-reset"),
            key=lambda record: record.entry.created_in_revision,
            default=None,
        )
        reset_revision = 0 if latest_reset is None else latest_reset.entry.created_in_revision
        chapter_token = "base" if latest_reset is None else latest_reset.entry.entry_version_id[:12]
        marker = f"[{chapter_token}:{turn_id[:24]}]"
        if any(
            record.entry.text.startswith(marker) and record.entry.created_in_revision >= reset_revision
            for record in entries.entries
        ):
            return {"status": "already_saved", "turn_id": turn_id}

        turn = (
            sum(
                1
                for record in entries.entries
                if record.entry.kind == "player-choice" and record.entry.created_in_revision >= reset_revision
            )
            + 1
        )
        choice_text = f"{marker} 第 {turn} 回合：玩家选择「{move}」。"
        scene_text = f"{marker} 第 {turn} 回合剧情：{story}"
        saved = await memory.remember(
            RememberMemoryRequest(
                entries=(
                    MemoryEntryInput(kind="player-choice", text=choice_text),
                    MemoryEntryInput(kind="story-scene", text=scene_text),
                ),
            ),
        )
        return {
            "status": "saved",
            "turn": turn,
            "turn_id": turn_id,
            "memory_ref": saved.memory_ref.model_dump(mode="json"),
        }

    async def reset(self, user_id: str) -> dict[str, Any]:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope(user_id)
        chapter_id = uuid4().hex[:12]
        saved = await runtime.memory.for_scope(scope_id).remember(
            RememberMemoryRequest(
                entries=(
                    MemoryEntryInput(
                        kind="story-reset",
                        text=(f"故事重置 [{chapter_id}]：丢弃此前剧情，从离谱旅行社的午夜大厅重新开始。"),
                    ),
                ),
            ),
        )
        return {
            "status": "reset",
            "memory_ref": saved.memory_ref.model_dump(mode="json"),
        }

    async def list_memories(self, user_id: str) -> dict[str, Any]:
        runtime = self._required_runtime()
        scope_id = await self._ensure_scope(user_id)
        await self._seed_if_empty(scope_id)
        page = await runtime.memory.for_scope(scope_id).list()
        return {
            "scope_id": scope_id,
            "entries": [
                {
                    "kind": record.entry.kind,
                    "text": record.entry.text,
                    "state": record.state,
                    "revision": record.entry.created_in_revision,
                    "citation": record.citation.model_dump(mode="json"),
                }
                for record in page.entries
            ],
        }

    async def _ensure_scope(self, user_id: str) -> str:
        normalized = user_id.strip() or "anonymous"
        cache_key = _user_key(normalized)
        cached = self._scope_cache.get(cache_key)
        if cached is not None:
            return cached
        runtime = self._required_runtime()
        if runtime.scopes is None:
            raise RuntimeError("PowerContext Scope registry is unavailable")
        scope = await runtime.scopes.create(
            ScopeDraft(
                title=f"Outlandish Travel Agency {cache_key[:12]}",
                summary="A playful cross-session story world with player choices and remembered consequences.",
                idempotency_key=f"dify-outlandish-travel:v1:{cache_key}",
            ),
        )
        self._scope_cache[cache_key] = scope.scope_id
        return scope.scope_id

    async def _seed_if_empty(self, scope_id: str) -> None:
        runtime = self._required_runtime()
        memory = runtime.memory.for_scope(scope_id)
        current = await memory.list()
        existing_kinds = {record.entry.kind for record in current.entries}
        missing = tuple(entry for entry in SEED_MEMORIES if entry.kind not in existing_kinds)
        if missing:
            await memory.remember(RememberMemoryRequest(entries=missing))

    @staticmethod
    def _evidence(
        text: str,
        score: float,
        matched_by: tuple[str, ...],
        citation: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "text": text,
            "score": round(score, 4),
            "matched_by": list(matched_by),
            "citation": citation,
        }

    def _required_runtime(self) -> BuiltinRuntime:
        if self._runtime is None:
            raise RuntimeError("StoryMemory has not been started")
        return self._runtime
