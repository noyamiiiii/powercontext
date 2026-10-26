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

"""Physical-page PDF Sources and deterministic evidence-page retrieval."""

# ruff: noqa: TRY003, TRY301

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBytes, StrictInt, field_validator, model_validator

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceMaterialization,
    TextEvidence,
)

PDF_PAGE_SOURCE_NAME = "pdf-page"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_WORD_PATTERN = re.compile(r"[^\W_]+")
_SENTENCE_INSTRUCTION = re.compile(
    r"^\s*(?:please\s+)?(?:answer|respond|give a response|assume that you are|"
    r"respond to the question|retrieve|use only)\b",
    re.IGNORECASE,
)
_QUERY_STOP_WORDS = frozenset({
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "calculate",
    "calculation",
    "can",
    "could",
    "define",
    "directly",
    "do",
    "does",
    "following",
    "for",
    "from",
    "give",
    "has",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "please",
    "question",
    "respond",
    "shown",
    "state",
    "that",
    "the",
    "their",
    "then",
    "this",
    "to",
    "use",
    "using",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "would",
})
_DOCUMENT_COMMON_TERMS = frozenset({
    "annual",
    "company",
    "corporation",
    "financial",
    "form",
    "inc",
    "report",
    "reports",
    "table",
    "year",
    "years",
})
_QUERY_EXPANSIONS = {
    "capex": ("capital", "expenditures", "property", "plant", "equipment"),
    "cogs": ("cost", "sales"),
    "ebitda": ("operating", "income", "depreciation", "amortization"),
    "employees": ("headcount", "employee", "workforce"),
    "employee": ("headcount", "employees", "workforce"),
    "fcf": ("free", "cash", "flow"),
    "geographies": ("geographic", "regions", "countries", "markets"),
    "geography": ("geographic", "regions", "countries", "markets"),
    "headcount": ("employees", "employee", "workforce"),
    "lawsuit": ("litigation", "proceedings", "claims", "legal"),
    "lawsuits": ("litigation", "proceedings", "claims", "legal"),
    "legal": ("litigation", "proceedings", "claims", "contingencies"),
    "margin": ("operating", "income", "net", "sales", "revenue"),
    "opex": ("operating", "expenses"),
    "operates": ("operations", "operating", "markets", "regions"),
    "ppne": ("property", "plant", "equipment", "net"),
    "rd": ("research", "development"),
    "revenue": ("net", "sales", "revenues"),
    "sales": ("revenue", "net", "sales"),
}


class PDFDocumentInput(BaseModel):
    """A complete PDF file together with its caller-selected document identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    content: StrictBytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")
        return value


class PDFPageInput(BaseModel):
    """One extracted physical PDF page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_sha256: Annotated[str, Field(pattern=_SHA256_PATTERN)]
    page_number: Annotated[StrictInt, Field(gt=0)]
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")
        return value


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page, or fail without returning partial output."""

    from pypdf import PdfReader

    content = bytes(value.content)
    if not content or b"%PDF-" not in content[:1024]:
        raise ValueError("PDF content is empty or does not have a PDF header")
    document_sha256 = hashlib.sha256(content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a non-empty password")
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=document_sha256,
                page_number=page_number,
                text=page.extract_text() or "",
            )
            for page_number, page in enumerate(reader.pages, start=1)
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF could not be parsed completely") from error
    return pages


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Return a compact identity stable across process restarts."""

    page = PDFPageInput(document_id=document_id, document_sha256=document_sha256, page_number=page_number, text="")
    try:
        document_identity = hashlib.sha256(page.document_id.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as error:
        raise ValueError("document_id must be valid UTF-8 text") from error
    source_id = f"{PDF_PAGE_SOURCE_NAME}:{page.page_number}:{page.document_sha256}:{document_identity}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"PDF page source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


class PDFPageSource(Source):
    """A captured Source representing one immutable physical PDF page."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str

    @model_validator(mode="after")
    def validate_source_identity(self) -> PDFPageSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the Source name")
        if self.source_id != pdf_page_source_id(self.document_id, self.document_sha256, self.page_number):
            raise ValueError("source_id must match the PDF page identity")
        return self


class PDFPageSourceAdapter:
    """Resolve and read physical-page Sources."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one physical PDF page as canonical text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    version="1",
    projections=(PDFPageTextEvidenceProjection(),),
)


@dataclass
class _RankedPage:
    memory_ref: ArtifactRef
    entry_id: str
    entry_version_id: str
    text: str
    channel_score: float = 0.0


_PDFPageLocation = tuple[str, str, int]
_MemoryEntryKey = tuple[str, int, str, str]


async def search_pdf_pages(memory: object, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Search a scoped Memory and return distinct real page citations."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")

    from powercontext.builtin.runtime import SearchMemoryRequest

    queries = _search_queries(question)
    query_terms, expanded_terms = _query_term_weights(question)
    candidates: dict[tuple[str, int, str, str], _RankedPage] = {}
    candidate_limit = max(80, limit * 5)
    for channel, query in enumerate(queries):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=candidate_limit))
        for rank, hit in enumerate(page.hits):
            key = (hit.memory_ref.artifact_id, hit.memory_ref.revision, hit.entry_id, hit.entry_version_id)
            candidate = candidates.get(key)
            if candidate is None:
                candidate = _RankedPage(
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                    text=hit.text,
                )
                candidates[key] = candidate
            candidate.channel_score += (1.0 if channel == 0 else 0.45) / (rank + 1)

    ranked = sorted(
        candidates.values(),
        key=lambda candidate: (
            -_page_rank(candidate.text, query_terms, expanded_terms, candidate.channel_score),
            candidate.entry_id,
            candidate.entry_version_id,
        ),
    )
    page_citations, locations = await _pdf_page_citations(memory)
    page_ranked = tuple(
        candidate
        for candidate in ranked
        if (
            candidate.memory_ref.artifact_id,
            candidate.memory_ref.revision,
            candidate.entry_id,
            candidate.entry_version_id,
        )
        in locations
    )
    primary = [
        MemoryCitation(
            memory_ref=candidate.memory_ref,
            entry_id=candidate.entry_id,
            entry_version_id=candidate.entry_version_id,
        )
        for candidate in (page_ranked if page_citations else ranked)[:limit]
    ]
    if not page_citations:
        return tuple(primary)
    return tuple(_stratified_page_citations(primary, locations, page_citations, limit))


async def _pdf_page_citations(
    memory: object,
) -> tuple[dict[_PDFPageLocation, MemoryCitation], dict[_MemoryEntryKey, tuple[_PDFPageLocation, ...]]]:
    list_entries = getattr(memory, "list", None)
    if not callable(list_entries):
        return {}, {}
    page = await list_entries()
    by_location: dict[_PDFPageLocation, MemoryCitation] = {}
    by_entry: dict[_MemoryEntryKey, tuple[_PDFPageLocation, ...]] = {}
    for record in page.entries:
        citation = record.citation
        locations = tuple(
            location
            for source in record.entry.sources
            if source.source_type == PDF_PAGE_SOURCE_NAME
            if (location := _pdf_page_location(source.source_id)) is not None
        )
        if not locations:
            continue
        key = (
            citation.memory_ref.artifact_id,
            citation.memory_ref.revision,
            citation.entry_id,
            citation.entry_version_id,
        )
        by_entry[key] = locations
        for location in locations:
            by_location.setdefault(location, citation)
    return by_location, by_entry


def _pdf_page_location(source_id: str) -> _PDFPageLocation | None:
    parts = source_id.split(":")
    if len(parts) != 4 or parts[0] != PDF_PAGE_SOURCE_NAME:
        return None
    _, page_text, document_sha256, document_id_hash = parts
    if not page_text.isdigit() or not re.fullmatch(_SHA256_PATTERN, document_sha256):
        return None
    if not re.fullmatch(_SHA256_PATTERN, document_id_hash):
        return None
    page_number = int(page_text)
    if page_number < 1:
        return None
    return document_sha256, document_id_hash, page_number


def _stratified_page_citations(
    primary: Sequence[MemoryCitation],
    locations: dict[_MemoryEntryKey, tuple[_PDFPageLocation, ...]],
    page_citations: dict[_PDFPageLocation, MemoryCitation],
    limit: int,
) -> list[MemoryCitation]:
    selected: list[MemoryCitation] = []
    seen: set[tuple[str, int, str, str]] = set()

    def add(citation: MemoryCitation) -> None:
        key = (
            citation.memory_ref.artifact_id,
            citation.memory_ref.revision,
            citation.entry_id,
            citation.entry_version_id,
        )
        if len(selected) < limit and key not in seen:
            seen.add(key)
            selected.append(citation)

    reserved_neighbors = min(6, max(3, limit // 5))
    primary_quota = max(1, limit - reserved_neighbors)
    for citation in primary[:primary_quota]:
        add(citation)
    ordered_boundaries = _page_clusters(primary, locations)
    for page_side in (0, 1):
        for _rank, document_sha256, document_id_hash, start, end in ordered_boundaries:
            page_number = start - 1 if page_side == 0 else end + 1
            neighbor = page_citations.get((document_sha256, document_id_hash, page_number))
            if neighbor is not None:
                add(neighbor)
    for citation in primary:
        add(citation)
    return selected


def _page_clusters(
    primary: Sequence[MemoryCitation],
    locations: dict[_MemoryEntryKey, tuple[_PDFPageLocation, ...]],
) -> list[tuple[int, str, str, int, int]]:
    clusters: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for rank, citation in enumerate(primary):
        key = (
            citation.memory_ref.artifact_id,
            citation.memory_ref.revision,
            citation.entry_id,
            citation.entry_version_id,
        )
        for document_sha256, document_id_hash, page_number in locations.get(key, ()):
            clusters.setdefault((document_sha256, document_id_hash), []).append((page_number, rank))
    boundaries = []
    for (document_sha256, document_id_hash), points in clusters.items():
        ordered = sorted(points)
        start = previous = ordered[0][0]
        best_rank = ordered[0][1]
        for page_number, rank in ordered[1:]:
            if page_number - previous <= 2:
                previous = page_number
                best_rank = min(best_rank, rank)
                continue
            boundaries.append((best_rank, document_sha256, document_id_hash, start, previous))
            start = previous = page_number
            best_rank = rank
        boundaries.append((best_rank, document_sha256, document_id_hash, start, previous))
    return sorted(boundaries)


def _search_queries(question: str) -> tuple[str, ...]:
    normalized = " ".join(question.split())
    terms = _query_terms(question)
    if not terms:
        return (normalized,)

    selected = _ordered_unique_terms(terms)
    expanded = _expanded_terms(selected)
    queries = [normalized, " ".join(selected), " ".join(expanded)]
    queries.extend(term for term in _specific_terms(expanded)[:12])
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def _query_term_weights(question: str) -> tuple[dict[str, float], dict[str, float]]:
    raw_terms = _ordered_unique_terms(_query_terms(question))
    terms = _ordered_unique_terms([_normalize_term(term) for term in raw_terms])
    original: dict[str, float] = {}
    for index, term in enumerate(terms):
        weight = 1.0
        if any(character.isdigit() for character in term):
            weight += 1.1
        if len(term) >= 8:
            weight += 0.35
        if index > 24:
            weight *= 0.5
        original[term] = weight
    expanded: dict[str, float] = {}
    for raw_term in raw_terms:
        for expansion in _term_expansions(raw_term):
            term = _normalize_term(expansion)
            if term not in original:
                expanded[term] = 0.35
    return original, expanded


def _page_rank(
    text: str,
    query_terms: dict[str, float],
    expanded_terms: dict[str, float],
    channel_score: float,
) -> float:
    lines = text.splitlines()
    body = "\n".join(lines[1:]) if len(lines) > 1 else text
    terms = Counter(_normalized_tokens(body))
    weights = {**expanded_terms, **query_terms}
    total_weight = sum(weights.values()) or 1.0
    matched_weight = sum(weight for term, weight in weights.items() if terms[term])
    coverage = matched_weight / total_weight
    length_normalization = 1.0 + math.log1p(len(terms)) / 12.0
    frequency = sum(
        weight * min(3, terms[term]) / length_normalization for term, weight in weights.items() if terms[term]
    )
    ordered_query = tuple(query_terms)
    body_sequence = _normalized_tokens(body)
    body_pairs = set(pairwise(body_sequence))
    phrase_hits = sum(pair in body_pairs for pair in pairwise(ordered_query))
    numeric_hits = sum(
        weight for term, weight in query_terms.items() if any(character.isdigit() for character in term) and terms[term]
    )
    table_signal = 1.0 if re.search(r"\b(?:total|statement|consolidated|million|thousand)\b", body, re.I) else 0.0
    return (
        8.0 * coverage
        + min(4.0, frequency)
        + min(3.0, phrase_hits)
        + 0.8 * numeric_hits
        + 0.35 * table_signal
        + 2.5 * channel_score
    )


def _query_terms(question: str) -> tuple[str, ...]:
    pieces = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", question):
        if not _SENTENCE_INSTRUCTION.match(sentence):
            pieces.append(sentence)
            continue
        if ":" in sentence:
            pieces.append(sentence.split(":", 1)[1])
            continue
        question_start = re.search(r"\b(?:what|which|who|how|when|where|why)\b", sentence, re.IGNORECASE)
        if question_start is not None:
            pieces.append(sentence[question_start.start() :])
    content = " ".join(pieces) if pieces else question
    terms = [
        term for term in _raw_tokens(content) if term not in _QUERY_STOP_WORDS and term not in _DOCUMENT_COMMON_TERMS
    ]
    return tuple(terms)


def _raw_tokens(value: str) -> tuple[str, ...]:
    normalized = value.casefold()
    for pattern, replacement in (
        (r"\br\s*&\s*d\b", "research development"),
        (r"\bpp\s*&\s*e\b", "property plant equipment"),
        (r"\bm\s*&\s*a\b", "mergers acquisitions"),
        (r"\bsg\s*&\s*a\b", "selling general administrative"),
        (r"\bd\s*&\s*a\b", "depreciation amortization"),
    ):
        normalized = re.sub(pattern, replacement, normalized)
    return tuple(match.group() for match in _WORD_PATTERN.finditer(normalized))


def _normalized_tokens(value: str) -> tuple[str, ...]:
    return tuple(_normalize_term(term) for term in _raw_tokens(value))


def _normalize_term(term: str) -> str:
    if term.isdigit() or len(term) <= 3:
        return term
    for suffix, replacement in (
        ("ational", "ate"),
        ("ations", "ate"),
        ("ation", "ate"),
        ("ating", "ate"),
        ("ated", "ate"),
        ("ates", "ate"),
        ("ies", "y"),
        ("ing", ""),
        ("ed", ""),
    ):
        if term.endswith(suffix) and len(term) - len(suffix) >= 3:
            term = term[: -len(suffix)] + replacement
            break
    if term.endswith("s") and not term.endswith(("ss", "is", "us")) and len(term) > 4:
        term = term[:-1]
    return term


def _ordered_unique_terms(terms: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(term for term in terms if term))


def _expanded_terms(terms: Sequence[str]) -> list[str]:
    ordered = list(terms)
    for term in terms:
        ordered.extend(_term_expansions(term))
    return _ordered_unique_terms(ordered)


def _term_expansions(term: str) -> tuple[str, ...]:
    expansions = list(_QUERY_EXPANSIONS.get(term, ()))
    year = re.fullmatch(r"fy'?(\d{2}|\d{4})", term)
    if year:
        value = year.group(1)
        expansions.append(value if len(value) == 4 else f"20{value}")
    return tuple(expansions)


def _specific_terms(terms: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            dict.fromkeys(terms),
            key=lambda term: (
                not any(character.isdigit() for character in term),
                "-" not in term,
                -len(term),
                terms.index(term),
            ),
        )
    )


__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDFPageSourceAdapter",
    "PDFPageTextEvidenceProjection",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
