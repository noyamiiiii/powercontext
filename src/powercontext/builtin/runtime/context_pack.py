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

"""Canonical full and incremental Context Pack wire formats."""

# ruff: noqa: TRY003

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

CONTEXT_PACK_SCHEMA: Final = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA: Final = "powercontext.context-pack-delta.v1"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ContextPackError(ValueError):
    """A malformed or inconsistent Context Pack protocol value."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One complete Context Pack."""

    items: tuple[bytes, ...]
    digest: str

    def __post_init__(self) -> None:
        items = _normalize_items(self.items)
        object.__setattr__(self, "items", items)
        if self.digest != _pack_digest(items):
            raise ContextPackError("Context Pack digest does not match its items")

    @classmethod
    def build(cls, items: Iterable[bytes], /) -> ContextPack:
        normalized = _normalize_items(items)
        return cls(items=normalized, digest=_pack_digest(normalized))

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if not isinstance(content, str | bytes):
            raise ContextPackError("Context Pack content must be text or UTF-8 bytes")
        try:
            raw = content.encode("utf-8") if isinstance(content, str) else content
            raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ContextPackError("Context Pack content must be valid UTF-8") from error

        items: list[bytes] = []
        start = 0
        while start < len(raw):
            end = min(start + chunk_bytes, len(raw))
            if end < len(raw):
                while end > start and raw[end] >> 6 == 0b10:
                    end -= 1
                if end == start:
                    raise ContextPackError("chunk_bytes is too small for one UTF-8 code point")
            items.append(raw[start:end])
            start = end
        return cls.build(tuple(items))

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        items = _encoded_items(self.items)
        payload = {
            "schema": CONTEXT_PACK_SCHEMA,
            "items": items,
            "digest": self.digest,
            "byte_count": 0,
        }
        for _ in range(4):
            raw = _canonical_json(payload)
            actual = len(raw)
            if payload["byte_count"] == actual:
                return raw
            payload["byte_count"] = actual
        raise ContextPackError("Context Pack byte_count did not converge")

    @classmethod
    def from_bytes(cls, value: bytes) -> ContextPack:
        payload, raw = _decode_object(value, "Context Pack")
        if set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("Context Pack must contain exactly schema, items, digest, and byte_count")
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("unsupported Context Pack schema")
        if type(payload["byte_count"]) is not int or payload["byte_count"] != len(raw):
            raise ContextPackError("Context Pack byte_count does not match its wire size")
        items = _decode_items(payload["items"], "Context Pack items")
        pack = cls.build(items)
        if payload["digest"] != pack.digest:
            raise ContextPackError("Context Pack digest does not match its items")
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """One prefix-reuse delta from a complete base Pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if not _is_digest(self.base_digest) or not _is_digest(self.target_digest):
            raise ContextPackError("Context Pack delta digests must use sha256:<hex>")
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        object.__setattr__(self, "appended", _normalize_items(self.appended))

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("Context Pack delta requires complete base and target packs")
        prefix_items = 0
        for base_item, target_item in zip(base.items, target.items, strict=False):
            if base_item != target_item:
                break
            prefix_items += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix_items,
            appended=target.items[prefix_items:],
        )

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _canonical_json({
            "schema": CONTEXT_PACK_DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encoded_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, value: bytes) -> ContextPackDelta:
        payload, _raw = _decode_object(value, "Context Pack delta")
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            raise ContextPackError("Context Pack delta fields do not match the protocol")
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("unsupported Context Pack delta schema")
        delta = cls(
            base_digest=payload["base_digest"],
            target_digest=payload["target_digest"],
            prefix_items=payload["prefix_items"],
            appended=_decode_items(payload["appended"], "Context Pack delta appended"),
        )
        return delta


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("apply_context_pack_delta requires a base Pack and delta")
    if delta.base_digest != base.digest:
        raise ContextPackError("Context Pack delta was created for a different base")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("Context Pack delta prefix exceeds the base item count")
    target = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("reconstructed Context Pack does not match the target digest")
    return target


def _normalize_items(items: Iterable[bytes]) -> tuple[bytes, ...]:
    try:
        values = tuple(items)
    except TypeError as error:
        raise ContextPackError("Context Pack items must be an iterable of bytes") from error
    if not all(isinstance(item, bytes) for item in values):
        raise ContextPackError("Context Pack items must be bytes")
    return values


def _encoded_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: Any, field: str) -> tuple[bytes, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ContextPackError(f"{field} must be a Base64 string array")
    items = []
    for encoded in value:
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ContextPackError(f"{field} contains invalid Base64") from error
        if base64.b64encode(decoded).decode("ascii") != encoded:
            raise ContextPackError(f"{field} contains non-canonical Base64")
        items.append(decoded)
    return tuple(items)


def _pack_digest(items: tuple[bytes, ...]) -> str:
    canonical = _canonical_json({"schema": CONTEXT_PACK_SCHEMA, "items": _encoded_items(items)})
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _decode_object(value: bytes, label: str) -> tuple[dict[str, Any], bytes]:
    if not isinstance(value, bytes):
        raise ContextPackError(f"{label} wire value must be bytes")
    try:
        text = value.decode("utf-8", errors="strict")
        payload = json.loads(text, parse_constant=_reject_non_finite_json)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ContextPackError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ContextPackError(f"{label} JSON must be an object")
    return payload, value


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST_RE.fullmatch(value) is not None


def _reject_non_finite_json(value: str) -> None:
    raise ContextPackError(f"non-finite JSON number {value!r} is not allowed")


__all__ = [
    "CONTEXT_PACK_DELTA_SCHEMA",
    "CONTEXT_PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
