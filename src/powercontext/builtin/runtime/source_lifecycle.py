# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Durable evidence dependency lifecycles for Memory and Topic Memory."""

# ruff: noqa: TRY003

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import delete, insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.codec import dump_model, load_model
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_GRAPHS_TABLE,
    SOURCE_LIFECYCLE_TOPIC_STATUS_TABLE,
)
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from powercontext.builtin.runtime.application import BuiltinRuntime

_PositiveInt = Annotated[StrictInt, Field(gt=0)]
_NodeKind = Literal["source", "memory", "topic"]
_Policy = Literal["all", "any"]


class SourceLifecycleError(ValueError):
    """A graph, event, or lifecycle reference violates the public contract."""


class SourceLifecycleEvent(BaseModel):
    """One ordered availability event for a registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: _PositiveInt
    sequence: _PositiveInt
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("lifecycle event text must be non-blank")
        return value


class _LifecycleNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    kind: _NodeKind
    source_ref: SourceRef | None = None
    memory_citation: MemoryCitation | None = None
    artifact_ref: ArtifactRef | None = None
    revision: _PositiveInt | None = None
    parents: tuple[str, ...] = ()
    policy: _Policy | None = None
    available: StrictBool
    last_sequence: StrictInt = Field(default=0, ge=0)
    last_event_available: StrictBool | None = None
    last_reason: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> _LifecycleNode:
        references = (self.source_ref, self.memory_citation, self.artifact_ref)
        if sum(reference is not None for reference in references) != 1:
            raise ValueError("lifecycle node must contain exactly one reference")
        if self.kind == "source":
            if self.source_ref is None or self.revision is None or self.parents or self.policy is not None:
                raise ValueError("Source lifecycle node shape is invalid")
        elif self.kind == "memory":
            if self.memory_citation is None or self.revision is not None or not self.parents or self.policy is None:
                raise ValueError("Memory lifecycle node shape is invalid")
        elif self.artifact_ref is None or self.revision is not None or not self.parents or self.policy is None:
            raise ValueError("Topic lifecycle node shape is invalid")
        return self


class _LifecycleGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nodes: tuple[_LifecycleNode, ...] = ()

    @model_validator(mode="after")
    def validate_identities(self) -> _LifecycleGraph:
        node_ids = tuple(node.node_id for node in self.nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("lifecycle node identities must be unique")
        return self


class SourceLifecycleApplication:
    """Select evidence lifecycle services by Scope."""

    def __init__(self, runtime: BuiltinRuntime) -> None:
        self._runtime = runtime

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleApplication:
        return ScopedSourceLifecycleApplication(self._runtime, scope_id)


class ScopedSourceLifecycleApplication:
    """Register and propagate evidence availability within one Scope."""

    def __init__(self, runtime: BuiltinRuntime, scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        _validate_node_id(node_id)
        _validate_positive_int("revision", revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source_ref must be a SourceRef")
        await self._require_source(source_ref)
        node = _LifecycleNode(
            node_id=node_id,
            kind="source",
            source_ref=source_ref,
            revision=revision,
            available=True,
        )
        await self._register(node)

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        *,
        parents: Sequence[str],
        policy: _Policy,
    ) -> None:
        _validate_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("citation must be a MemoryCitation")
        await self._require_memory(citation)
        node = _derived_node(
            node_id,
            "memory",
            parents=parents,
            policy=policy,
            memory_citation=citation,
        )
        await self._register(node)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        *,
        parents: Sequence[str],
        policy: _Policy,
    ) -> None:
        _validate_node_id(node_id)
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("artifact_ref must reference Topic Memory")
        await self._require_topic(artifact_ref)
        node = _derived_node(
            node_id,
            "topic",
            parents=parents,
            policy=policy,
            artifact_ref=artifact_ref,
        )
        await self._register(node)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event must be a SourceLifecycleEvent")
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            async with self._database.transaction() as connection:
                graph = await _load_graph(connection, self.scope_id, for_update=True)
                node = _node_or_error(graph, event.node_id)
                if node.kind != "source" or node.revision is None:
                    raise SourceLifecycleError("lifecycle events apply only to Sources")
                if event.revision != node.revision:
                    raise SourceLifecycleError("lifecycle event revision mismatch")
                if event.sequence < node.last_sequence:
                    raise SourceLifecycleError("lifecycle event sequence moved backwards")
                if event.sequence == node.last_sequence:
                    if (
                        node.last_sequence == 0
                        or node.last_event_available != event.available
                        or node.last_reason != event.reason
                    ):
                        raise SourceLifecycleError("lifecycle event identity conflicts with its sequence")
                    return _active_ids(graph)

                nodes = list(graph.nodes)
                nodes[graph.nodes.index(node)] = node.model_copy(
                    update={
                        "available": event.available,
                        "last_sequence": event.sequence,
                        "last_event_available": event.available,
                        "last_reason": event.reason,
                    }
                )
                graph = _recompute(_LifecycleGraph(nodes=tuple(nodes)))

            await self._sync_memory_states(graph, reason=event.reason)
            async with self._database.transaction() as connection:
                await self._save_graph_and_topics(connection, graph)
            return _active_ids(graph)

    async def resolve(self, node_id: str, *, purpose: str) -> SourceRef | MemoryCitation | ArtifactRef:
        _validate_node_id(node_id)
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("unknown lifecycle resolution purpose")
        async with self._database.transaction() as connection:
            graph = await _load_graph(connection, self.scope_id)
        node = _node_or_error(graph, node_id)
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError("lifecycle node is unavailable for generation")
        return _node_reference(node)

    async def _register(self, node: _LifecycleNode) -> None:
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            registered: _LifecycleNode | None = None
            async with self._database.transaction() as connection:
                graph = await _load_graph(connection, self.scope_id, for_update=True)
                existing = next((item for item in graph.nodes if item.node_id == node.node_id), None)
                if existing is not None:
                    if _registration_binding(existing) != _registration_binding(node):
                        raise SourceLifecycleError("lifecycle node identity is already bound differently")
                    registered = existing
                else:
                    _validate_parents(graph, node)
                    graph = _recompute(_LifecycleGraph(nodes=(*graph.nodes, node)))
                    registered = next(item for item in graph.nodes if item.node_id == node.node_id)

            if registered.kind == "source":
                if existing is None:
                    async with self._database.transaction() as connection:
                        await self._save_graph_and_topics(connection, graph)
                return
            if registered.kind == "memory":
                await self._set_memory_available(registered, reason="lifecycle registration")
            async with self._database.transaction() as connection:
                await self._save_graph_and_topics(connection, graph)

    async def _sync_memory_states(self, graph: _LifecycleGraph, *, reason: str) -> None:
        for node in graph.nodes:
            if node.kind == "memory":
                await self._set_memory_available(node, reason=reason)

    async def _set_memory_available(self, node: _LifecycleNode, *, reason: str) -> None:
        citation = node.memory_citation
        if citation is None:
            raise SourceLifecycleError("Memory lifecycle node has no citation")
        try:
            async with self._runtime._context(self.scope_id) as context:
                service = context.artifacts.memory
                version = await service.validate_citation(citation)
                current = await service.head(citation.memory_ref.artifact_id)
                entries = await service.entries(current)
                current_entry = next(
                    (
                        entry
                        for entry in entries
                        if entry.entry_id == citation.entry_id and entry.entry_version_id == citation.entry_version_id
                    ),
                    None,
                )
                if current_entry is None or current_entry != version:
                    raise SourceLifecycleError(  # noqa: TRY301
                        "Memory citation is not present in the current head"
                    )
                manifest = {item.entry_id: item for item in current.content.manifest.entries}
                current_state = manifest[citation.entry_id].state
                target_state = "active" if node.available else "inactive"
                if current_state == target_state:
                    return
                if node.available:
                    await service.reactivate(current, entries=(current_entry,), reason=reason)
                else:
                    await service.forget(current, entries=(current_entry,), reason=reason)
        except SourceLifecycleError:
            raise
        except Exception as error:
            raise SourceLifecycleError("Memory lifecycle propagation failed") from error

    async def _save_graph_and_topics(self, connection: AsyncConnection, graph: _LifecycleGraph) -> None:
        table = SOURCE_LIFECYCLE_GRAPHS_TABLE
        payload = dump_model(graph, kind="source-lifecycle", name=self.scope_id)
        existing = await connection.scalar(select(table.c.scope_id).where(table.c.scope_id == self.scope_id))
        if existing is None:
            await connection.execute(insert(table).values(scope_id=self.scope_id, payload=payload))
        else:
            await connection.execute(update(table).where(table.c.scope_id == self.scope_id).values(payload=payload))

        statuses = SOURCE_LIFECYCLE_TOPIC_STATUS_TABLE
        await connection.execute(delete(statuses).where(statuses.c.scope_id == self.scope_id))
        availability_by_reference: dict[tuple[str, int], bool] = {}
        for node in graph.nodes:
            if node.kind != "topic" or node.artifact_ref is None:
                continue
            reference = (node.artifact_ref.artifact_id, node.artifact_ref.revision)
            availability_by_reference[reference] = availability_by_reference.get(reference, False) or node.available
        topic_rows = [
            {
                "scope_id": self.scope_id,
                "artifact_id": artifact_id,
                "revision": revision,
                "available": available,
            }
            for (artifact_id, revision), available in availability_by_reference.items()
        ]
        if topic_rows:
            await connection.execute(insert(statuses), topic_rows)

    async def _require_source(self, source_ref: SourceRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_source(
                source_ref.source_type,
                source_ref.source_id,
            )
        except Exception as error:
            raise SourceLifecycleError("registered Source is not readable") from error

    async def _require_memory(self, citation: MemoryCitation) -> None:
        try:
            async with self._runtime._context(self.scope_id) as context:
                await context.artifacts.memory.validate_citation(citation)
        except Exception as error:
            raise SourceLifecycleError("registered Memory citation is not readable") from error

    async def _require_topic(self, artifact_ref: ArtifactRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                artifact_ref.family,
                artifact_ref.artifact_id,
                artifact_ref.revision,
            )
        except Exception as error:
            raise SourceLifecycleError("registered Topic Memory reference is not readable") from error

    @property
    def _database(self) -> AsyncDatabase:
        database = getattr(self._runtime._provider, "database", None)
        if not isinstance(database, AsyncDatabase):
            raise SourceLifecycleError("lifecycle persistence is not configured")
        return database


def _derived_node(
    node_id: str,
    kind: Literal["memory", "topic"],
    *,
    parents: Sequence[str],
    policy: _Policy,
    memory_citation: MemoryCitation | None = None,
    artifact_ref: ArtifactRef | None = None,
) -> _LifecycleNode:
    normalized_parents = tuple(parents)
    if not normalized_parents:
        raise SourceLifecycleError("derived lifecycle nodes require at least one parent")
    if len(set(normalized_parents)) != len(normalized_parents):
        raise SourceLifecycleError("lifecycle parents must be unique")
    if policy not in {"all", "any"}:
        raise SourceLifecycleError("lifecycle policy must be all or any")
    return _LifecycleNode(
        node_id=node_id,
        kind=kind,
        memory_citation=memory_citation,
        artifact_ref=artifact_ref,
        parents=normalized_parents,
        policy=policy,
        available=False,
    )


def _validate_parents(graph: _LifecycleGraph, node: _LifecycleNode) -> None:
    known = {item.node_id for item in graph.nodes}
    if node.kind != "source":
        if not node.parents:
            raise SourceLifecycleError("derived lifecycle nodes require parents")
        if len(set(node.parents)) != len(node.parents):
            raise SourceLifecycleError("lifecycle parents must be unique")
        for parent in node.parents:
            if parent == node.node_id or parent not in known:
                raise SourceLifecycleError("lifecycle parent must be previously registered")


def _recompute(graph: _LifecycleGraph) -> _LifecycleGraph:
    availability: dict[str, bool] = {}
    nodes = []
    for node in graph.nodes:
        if node.kind == "source":
            available = node.available
        else:
            support = tuple(availability[parent] for parent in node.parents)
            available = all(support) if node.policy == "all" else any(support)
        availability[node.node_id] = available
        nodes.append(node.model_copy(update={"available": available}))
    return _LifecycleGraph(nodes=tuple(nodes))


def _active_ids(graph: _LifecycleGraph) -> list[str]:
    return sorted(node.node_id for node in graph.nodes if node.available)


def _node_or_error(graph: _LifecycleGraph, node_id: str) -> _LifecycleNode:
    for node in graph.nodes:
        if node.node_id == node_id:
            return node
    raise SourceLifecycleError("lifecycle node is not registered")


def _node_reference(node: _LifecycleNode) -> SourceRef | MemoryCitation | ArtifactRef:
    if node.source_ref is not None:
        return node.source_ref
    if node.memory_citation is not None:
        return node.memory_citation
    if node.artifact_ref is not None:
        return node.artifact_ref
    raise SourceLifecycleError("lifecycle node has no reference")


def _registration_binding(node: _LifecycleNode) -> tuple[Any, ...]:
    return (
        node.kind,
        node.source_ref,
        node.memory_citation,
        node.artifact_ref,
        node.revision,
        node.parents,
        node.policy,
    )


def _validate_node_id(node_id: str) -> None:
    if not isinstance(node_id, str) or not node_id or not node_id.strip():
        raise SourceLifecycleError("lifecycle node_id must be non-blank")


def _validate_positive_int(field: str, value: object) -> None:
    if type(value) is not int or value <= 0:
        raise SourceLifecycleError(f"{field} must be a positive integer")


async def _load_graph(
    connection: AsyncConnection,
    scope_id: str,
    /,
    *,
    for_update: bool = False,
) -> _LifecycleGraph:
    table = SOURCE_LIFECYCLE_GRAPHS_TABLE
    if for_update and connection.dialect.name == "sqlite":
        await connection.execute(update(table).where(table.c.scope_id == scope_id).values(payload=table.c.payload))
    statement = select(table.c.payload).where(table.c.scope_id == scope_id)
    if for_update:
        statement = statement.with_for_update()
    payload = await connection.scalar(statement)
    if payload is None:
        return _LifecycleGraph()
    return load_model(_LifecycleGraph, payload, kind="source-lifecycle", name=scope_id)


__all__ = [
    "ScopedSourceLifecycleApplication",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
