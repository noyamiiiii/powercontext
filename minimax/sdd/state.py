"""Task checkpoints are written and read through PowerContext's builtin runtime."""
import json
from pathlib import Path
from uuid import uuid4
from powercontext.builtin.runtime import BuiltinConfig, CaptureSource, open_builtin_runtime
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.scope.models import ScopeDraft
from .common import now

class TaskState:
    def __init__(self, runtime):
        self.directory = Path(runtime).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{self.directory / 'powercontext.db'}"))

    async def access(self, task_id, payload=None):
        if payload is not None:
            if not isinstance(payload, dict) or {"task_id", "time"}.intersection(payload):
                raise ValueError("Checkpoint must be an object without reserved task_id or time fields")
            for name in ("done", "todo"):
                if not isinstance(payload.get(name), list) or not all(isinstance(x, str) for x in payload[name]):
                    raise ValueError(f"Checkpoint {name} must be a list of strings")
            if not isinstance(payload.get("validations"), list):
                raise ValueError("Checkpoint validations must be a list")
        # Every invocation opens and closes the actual PowerContext runtime.
        async with open_builtin_runtime(self.config, scheduler_path=self.directory / "scheduler.db") as pc:
            scope = await pc.scopes.create(ScopeDraft(title=f"SDD: {task_id}",
                summary="Engineering task progress and verification", idempotency_key=f"minimax-sdd:{task_id}"))
            if payload is not None:
                record = {"task_id": task_id, "time": now(), **payload}
                receipt = await pc.sources.for_scope(scope.scope_id).capture(CaptureSource(
                    source_id=str(uuid4()), content=json.dumps(record, ensure_ascii=False), metadata={"task_id": task_id}))
                return {"scope_id": scope.scope_id, "receipt": receipt.model_dump(mode="json"), "state": record}
            cursor = None
            latest = None
            while True:
                page = await pc.records.for_scope(scope.scope_id).list_sources(limit=100, cursor=cursor)
                for source in page.items:
                    raw = source.content
                    text = raw["content"] if isinstance(raw, dict) else raw
                    item = json.loads(text)
                    if item.get("task_id") == task_id and (latest is None or source.position > latest[0]):
                        latest = (source.position, source.source_id, item)
                cursor = page.next_cursor
                if cursor is None:
                    break
            return {"scope_id": scope.scope_id, "state": None if latest is None else latest[2],
                "source_id": None if latest is None else latest[1], "backend": "PowerContext builtin SQLite"}
