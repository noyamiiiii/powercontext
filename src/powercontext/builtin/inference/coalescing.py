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

"""Cross-call Embedding request coalescing with a bounded result cache."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile


@dataclass(frozen=True, slots=True)
class _EmbeddedValue:
    vector: EmbeddingVector
    batch_id: int | None
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    """Coalesce equal texts and cache successful vectors across calls."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size <= 0:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, int | float):
            raise ValueError("coalesce_ms must be a non-negative finite number")  # noqa: TRY003, TRY004
        if not math.isfinite(coalesce_ms) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative finite number")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003

        self._model = model
        self.profile: EmbeddingProfile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._operations: dict[str, asyncio.Future[_EmbeddedValue]] = {}
        self._queued: OrderedDict[str, None] = OrderedDict()
        self._timer: asyncio.TimerHandle | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._batch_id = 0
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return vectors in input order and charge only batches awaited by this call."""

        inputs = tuple(texts)
        if any(not isinstance(text, str) for text in inputs):
            raise ValueError("embedding texts must be strings")  # noqa: TRY003
        if not inputs:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        resolved, queued_new = self._resolve_inputs(inputs)
        if queued_new:
            if len(self._queued) >= self._max_batch_size:
                self._flush_ready()
            else:
                self._schedule_flush()

        values_list: list[_EmbeddedValue] = []
        for value in resolved:
            if isinstance(value, _EmbeddedValue):
                values_list.append(value)
            else:
                values_list.append(await asyncio.shield(value))
        values = tuple(values_list)
        return EmbeddingResult(
            vectors=tuple(value.vector for value in values),
            usage=_sum_usage(values),
        )

    def _resolve_inputs(
        self, inputs: tuple[str, ...]
    ) -> tuple[list[asyncio.Future[_EmbeddedValue] | _EmbeddedValue], bool]:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            if self._operations or self._tasks or self._queued or self._timer is not None:
                raise RuntimeError("CoalescingEmbeddingModel has work on another event loop")  # noqa: TRY003
            self._loop = loop

        resolved: list[asyncio.Future[_EmbeddedValue] | _EmbeddedValue] = []
        queued_new = False
        for text in inputs:
            cached = self._cache.get(text)
            if cached is not None:
                self._cache.move_to_end(text)
                resolved.append(_EmbeddedValue(cached, None, InferenceUsage(requests=0)))
                continue

            future = self._operations.get(text)
            if future is None:
                future = loop.create_future()
                self._operations[text] = future
                future.add_done_callback(lambda completed, value=text: self._finish_operation(value, completed))
                self._queued[text] = None
                queued_new = True
            resolved.append(future)
        return resolved, queued_new

    def _schedule_flush(self) -> None:
        if self._timer is not None or not self._queued:
            return
        loop = self._loop
        if loop is None:
            raise RuntimeError("CoalescingEmbeddingModel has no active event loop")  # noqa: TRY003
        self._timer = loop.call_later(self._coalesce_seconds, self._flush_ready)

    def _flush_ready(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._queued:
            return
        while self._queued:
            batch = tuple(list(self._queued)[: self._max_batch_size])
            for text in batch:
                self._queued.pop(text, None)
            task = asyncio.create_task(self._run_batch(batch))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            if len(self._queued) < self._max_batch_size:
                break
        if self._queued:
            self._schedule_flush()

    async def _run_batch(self, texts: tuple[str, ...]) -> None:
        self._batch_id += 1
        batch_id = self._batch_id
        try:
            result = await self._model.embed(texts)
            _validate_batch_result(texts, result)
            self._cache_vectors(texts, result.vectors)
            self._complete_batch(texts, result.vectors, batch_id, result.usage)
        except BaseException as error:
            for text in texts:
                future = self._operations.get(text)
                if future is not None and not future.done():
                    future.set_exception(error)
            if isinstance(error, asyncio.CancelledError):
                raise

    def _cache_vectors(self, texts: tuple[str, ...], vectors: tuple[EmbeddingVector, ...]) -> None:
        if self._cache_size == 0:
            return
        for text, vector in zip(texts, vectors, strict=True):
            self._cache[text] = vector
            self._cache.move_to_end(text)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def _complete_batch(
        self,
        texts: tuple[str, ...],
        vectors: tuple[EmbeddingVector, ...],
        batch_id: int,
        usage: InferenceUsage,
    ) -> None:
        for text, vector in zip(texts, vectors, strict=True):
            future = self._operations.get(text)
            if future is not None and not future.done():
                future.set_result(_EmbeddedValue(vector, batch_id, usage))

    def _finish_operation(self, text: str, completed: asyncio.Future[_EmbeddedValue]) -> None:
        if self._operations.get(text) is completed:
            self._operations.pop(text, None)
        if not completed.cancelled():
            completed.exception()


def _sum_usage(values: tuple[_EmbeddedValue, ...]) -> InferenceUsage:
    batches: dict[int, InferenceUsage] = {}
    for value in values:
        if value.batch_id is not None:
            batches[value.batch_id] = value.usage
    requests = sum(usage.requests for usage in batches.values())
    input_values = tuple(usage.input_tokens for usage in batches.values())
    output_values = tuple(usage.output_tokens for usage in batches.values())
    return InferenceUsage(
        requests=requests,
        input_tokens=_sum_optional(input_values),
        output_tokens=_sum_optional(output_values),
    )


def _validate_batch_result(texts: tuple[str, ...], result: EmbeddingResult) -> None:
    if len(result.vectors) != len(texts):
        raise ValueError("embedding provider returned the wrong number of vectors")  # noqa: TRY003


def _sum_optional(values: tuple[int | None, ...]) -> int | None:
    if not any(value is not None for value in values):
        return None
    return sum(value or 0 for value in values)


__all__ = ["CoalescingEmbeddingModel"]
