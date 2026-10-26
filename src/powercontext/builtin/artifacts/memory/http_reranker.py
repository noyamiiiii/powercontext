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

"""HTTP scoring adapter for Memory candidate reranking."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_RERANK_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score candidates in bounded HTTP batches and select across the full pool."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = HTTP_RERANK_POLICY_ID,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("HTTP reranker endpoint must be non-empty")  # noqa: TRY003
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("HTTP reranker batch_size must be a positive integer")  # noqa: TRY003
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError("HTTP reranker policy_id must be non-empty")  # noqa: TRY003
        self.endpoint = endpoint
        self.batch_size = batch_size
        self.policy_id = policy_id
        self._client = client

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate once and return the globally best original ranks."""

        _validate_bounds(len(candidates), limit)
        scores: dict[int, float] = {}
        request_count = 0

        for start in range(0, len(candidates), self.batch_size):
            batch = candidates[start : start + self.batch_size]
            expected_ranks = tuple(range(start + 1, start + len(batch) + 1))
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidate.text}
                    for rank, candidate in zip(expected_ranks, batch, strict=True)
                ],
            }
            response = await self._client.post(self.endpoint, json=payload)
            request_count += 1
            response.raise_for_status()
            batch_scores = _parse_scores(response.json(), expected_ranks)
            scores.update(batch_scores)

        selected_ranks = tuple(
            rank for rank, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        )
        return MemoryRerankDecision(
            selected_ranks=selected_ranks,
            usage=InferenceUsage(requests=request_count),
        )


def _parse_scores(payload: Any, expected_ranks: tuple[int, ...]) -> dict[int, float]:
    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("HTTP reranker response must contain exactly the scores field")  # noqa: TRY003
    values = payload["scores"]
    if not isinstance(values, list):
        raise ValueError("HTTP reranker scores must be a list")  # noqa: TRY003, TRY004

    parsed: dict[int, float] = {}
    for value in values:
        if not isinstance(value, Mapping) or set(value) != {"rank", "score"}:
            raise ValueError("each HTTP reranker score must contain exactly rank and score")  # noqa: TRY003
        rank = value["rank"]
        score = value["score"]
        if type(rank) is not int or rank not in expected_ranks:
            raise ValueError("HTTP reranker returned a rank outside its current batch")  # noqa: TRY003
        if rank in parsed:
            raise ValueError("HTTP reranker returned a duplicate rank")  # noqa: TRY003
        if isinstance(score, bool) or not isinstance(score, int | float) or not math.isfinite(score):
            raise ValueError("HTTP reranker scores must be finite numbers")  # noqa: TRY003
        parsed[rank] = float(score)

    if set(parsed) != set(expected_ranks):
        raise ValueError("HTTP reranker did not score every candidate in the batch")  # noqa: TRY003
    return parsed


def _validate_bounds(candidate_count: int, limit: int) -> None:
    if candidate_count < 1:
        raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
    if type(limit) is not int or limit < 1 or limit > candidate_count:
        raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003


__all__ = ["HTTP_RERANK_POLICY_ID", "HTTPMemoryReranker"]
