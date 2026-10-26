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

"""Pi v3 session branches captured as immutable event evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
    Source,
    SourceMaterialization,
    TextEvidence,
)

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_CONNECTOR_VERSION = "1"
_PI_CHECKPOINT_SCHEMA = "powercontext.pi-session-history.v1"


class PiSessionInput(BaseModel):
    """A complete Pi v3 JSONL archive and optional branch leaf."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: bytes
    leaf_id: str | None = None

    @field_validator("leaf_id")
    @classmethod
    def validate_leaf_id(cls, value: str | None) -> str | None:
        if value is not None and (not value or not value.strip()):
            raise ValueError("leaf_id must be non-empty when provided")  # noqa: TRY003
        return value


class PiEventInput(BaseModel):
    """One visible event retained from a selected Pi session branch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @field_validator("session_id", "event_id", "event_type", "role", "content")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Pi event text fields must be non-empty")  # noqa: TRY003
        return value

    @field_validator("parent_id")
    @classmethod
    def validate_parent_id(cls, value: str | None) -> str | None:
        if value is not None and (not value or not value.strip()):
            raise ValueError("parent_id must be non-empty when provided")  # noqa: TRY003
        return value


class PiEventSource(Source):
    """A captured Source representing one Pi session event."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_source_identity(self) -> PiEventSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the Source name")  # noqa: TRY003
        if self.source_id != _pi_event_source_id(self.session_id, self.event_id):
            raise ValueError("source_id must match the Pi event identity")  # noqa: TRY003
        return self


@dataclass(frozen=True, slots=True)
class _PiGraph:
    session_id: str
    nodes: Mapping[str, dict[str, Any]]
    order: tuple[str, ...]


class _CheckpointEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class _PiCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["powercontext.pi-session-history.v1"] = Field(alias="schema")
    events: tuple[_CheckpointEvent, ...]

    @model_validator(mode="after")
    def validate_unique_events(self) -> _PiCheckpoint:
        source_ids = tuple(event.source_id for event in self.events)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("checkpoint event identities must be unique")  # noqa: TRY003
        return self


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Return visible events from the selected root-to-leaf branch in order."""

    graph = _parse_pi_graph(value.content)
    return _events_for_leaf(graph, value.leaf_id)


def _events_for_leaf(graph: _PiGraph, leaf_id: str | None) -> tuple[PiEventInput, ...]:
    leaf_id = leaf_id if leaf_id is not None else graph.order[-1]
    if leaf_id not in graph.nodes:
        raise ValueError(f"Pi session leaf {leaf_id!r} was not found")  # noqa: TRY003

    branch_ids: list[str] = []
    current_id: str | None = leaf_id
    while current_id is not None:
        branch_ids.append(current_id)
        parent = graph.nodes[current_id].get("parentId")
        current_id = parent if isinstance(parent, str) else None
    branch_ids.reverse()

    events: list[PiEventInput] = []
    for event_id in branch_ids:
        event = _visible_event(graph.session_id, graph.nodes[event_id])
        if event is not None:
            _pi_event_source_id(event.session_id, event.event_id)
            events.append(event)
    return tuple(events)


def _parse_pi_graph(content: bytes) -> _PiGraph:
    records = _decode_pi_records(content)
    header = records[0]
    session_id = header.get("id")
    if (
        header.get("type") != "session"
        or type(header.get("version")) is not int
        or header.get("version") != 3
        or not isinstance(session_id, str)
        or not session_id.strip()
    ):
        raise ValueError("Pi session header must contain type=session, version=3, and a non-empty id")  # noqa: TRY003

    seen_ids = {session_id}
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records[1:]:
        _append_pi_node(record, seen_ids=seen_ids, nodes=nodes, order=order)

    if not order:
        raise ValueError("Pi session archive has no branch nodes")  # noqa: TRY003
    return _PiGraph(session_id=session_id, nodes=nodes, order=tuple(order))


def _decode_pi_records(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error  # noqa: TRY003

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_reject_non_finite_json)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid JSON at Pi session line {line_number}") from error  # noqa: TRY003
        if not isinstance(record, dict):
            raise ValueError(f"Pi session line {line_number} must be a JSON object")  # noqa: TRY003, TRY004
        records.append(record)

    if not records:
        raise ValueError("Pi session archive is empty")  # noqa: TRY003
    return records


def _append_pi_node(
    record: dict[str, Any],
    *,
    seen_ids: set[str],
    nodes: dict[str, dict[str, Any]],
    order: list[str],
) -> None:
    if record.get("type") == "session":
        raise ValueError("Pi session archive may contain only one session header")  # noqa: TRY003
    event_id = record.get("id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("every Pi session node must contain a non-empty id")  # noqa: TRY003
    if event_id in seen_ids:
        raise ValueError(f"duplicate Pi session node id {event_id!r}")  # noqa: TRY003
    if "parentId" not in record:
        raise ValueError(f"Pi session node {event_id!r} is missing parentId")  # noqa: TRY003
    parent_id = record["parentId"]
    if parent_id is not None:
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise ValueError(f"invalid parentId for Pi session node {event_id!r}")  # noqa: TRY003
        if parent_id not in nodes:
            raise ValueError(f"Pi session node {event_id!r} has a missing parent {parent_id!r}")  # noqa: TRY003
    seen_ids.add(event_id)
    nodes[event_id] = record
    order.append(event_id)


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")  # noqa: TRY003


def _visible_event(session_id: str, record: dict[str, Any]) -> PiEventInput | None:
    event_type = record.get("type")
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role or role == "system":
            return None
        if role == "toolResult":
            body = _tool_result_body(message)
        elif role == "bashExecution":
            body = _bash_execution_body(message)
        else:
            body = _message_body(message.get("content"))
    elif event_type in {"compaction", "branch_summary"}:
        role = event_type
        summary = record.get("summary")
        body = summary if isinstance(summary, str) else ""
    elif event_type == "custom_message":
        role = "custom"
        body = _text_body(record.get("content"))
    else:
        return None

    if not isinstance(role, str) or not body.strip():
        return None
    parent_id = record.get("parentId")
    return PiEventInput(
        session_id=session_id,
        event_id=record["id"],
        parent_id=parent_id if isinstance(parent_id, str) else None,
        event_type=record["type"],
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _message_body(content: object) -> str:
    if isinstance(content, str):
        return content if content.strip() else ""
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        elif block_type == "toolCall":
            tool_call = _tool_call_body(block)
            if tool_call:
                parts.append(tool_call)
    return "\n".join(parts)


def _text_body(content: object) -> str:
    if isinstance(content, str):
        return content if content.strip() else ""
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts)


def _tool_call_body(block: Mapping[str, Any]) -> str:
    name = block.get("name")
    call_id = block.get("id")
    if not isinstance(name, str) or not name or not isinstance(call_id, str) or not call_id:
        return ""
    arguments = block.get("arguments")
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"[tool_call {name} {call_id}] {encoded}"


def _tool_result_body(message: Mapping[str, Any]) -> str:
    tool_name = message.get("toolName")
    call_id = message.get("toolCallId")
    if not isinstance(tool_name, str) or not tool_name or not isinstance(call_id, str) or not call_id:
        return ""
    text = _text_body(message.get("content"))
    if not text.strip():
        return ""
    return f"[tool_result {tool_name} {call_id}] {text}"


def _bash_execution_body(message: Mapping[str, Any]) -> str:
    command = message.get("command")
    output = message.get("output")
    if not isinstance(command, str):
        command = ""
    if not isinstance(output, str):
        output = ""
    if not command.strip() and not output.strip():
        return ""
    return f"$ {command}\n{output}"


def _pi_event_source_id(session_id: str, event_id: str) -> str:
    if not session_id or not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be non-empty")  # noqa: TRY003
    if not event_id or not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id must be non-empty")  # noqa: TRY003
    try:
        source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    except UnicodeEncodeError as error:
        raise ValueError("Pi event identity components must be valid UTF-8 text") from error  # noqa: TRY003
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"Pi event source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


class PiEventSourceAdapter:
    """Resolve and read immutable Pi event Sources."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = _pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose a complete Pi event as canonical text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    version="1",
    projections=(PiEventTextEvidenceProjection(),),
)


class PiSessionConnector:
    """Collect new visible events from a selected Pi session branch."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_SESSION_CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_DEFINITION.name})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = PiSessionInput(content=b"", leaf_id=leaf_id).leaf_id if leaf_id is not None else None

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        graph = _parse_pi_graph(self.path.read_bytes())
        branch = _events_for_leaf(graph, self.leaf_id)
        visible_by_source = {
            _pi_event_source_id(event.session_id, event.event_id): event
            for event_id in graph.order
            if (event := _visible_event(graph.session_id, graph.nodes[event_id])) is not None
        }
        checkpoint = _read_checkpoint(session.checkpoint)
        imported = {entry.source_id: entry.digest for entry in checkpoint.events}

        for source_id, digest in imported.items():
            event = visible_by_source.get(source_id)
            if event is None or _record_digest(event.record) != digest:
                raise ValueError(f"previously imported Pi event {source_id!r} was changed or removed")  # noqa: TRY003

        completed = True
        new_entries: list[_CheckpointEvent] = []
        for event in branch:
            source_id = _pi_event_source_id(event.session_id, event.event_id)
            if source_id in imported:
                continue
            outcome = await session.submit(source_id, PI_EVENT_SOURCE_DEFINITION.name, event)
            if outcome.status is ConnectorSubmissionStatus.ACCEPTED:
                imported[source_id] = _record_digest(event.record)
                new_entries.append(_CheckpointEvent(source_id=source_id, digest=imported[source_id]))
            else:
                completed = False

        if not completed:
            return ConnectorRunCompletion(status=ConnectorRunStatus.INCOMPLETE, checkpoint=session.checkpoint)

        entries = tuple(
            _CheckpointEvent(source_id=source_id, digest=digest) for source_id, digest in sorted(imported.items())
        )
        checkpoint = _PiCheckpoint(schema_name=_PI_CHECKPOINT_SCHEMA, events=entries)
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint=checkpoint.model_dump(mode="json", by_alias=True),
        )


def _read_checkpoint(value: JsonValue | None) -> _PiCheckpoint:
    if value is None:
        return _PiCheckpoint(schema_name=_PI_CHECKPOINT_SCHEMA, events=())
    if not isinstance(value, dict):
        raise ValueError("Pi session connector checkpoint must be a JSON object")  # noqa: TRY003, TRY004
    try:
        return _PiCheckpoint.model_validate(value)
    except ValueError as error:
        raise ValueError("Pi session connector checkpoint is invalid") from error  # noqa: TRY003


def _record_digest(record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PI_SESSION_CONNECTOR_VERSION",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
