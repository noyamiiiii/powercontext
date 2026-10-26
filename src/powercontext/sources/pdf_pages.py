# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Complete physical PDF pages, durable provenance, and offline evidence retrieval."""

from __future__ import annotations

import hashlib
import io
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, StrictInt, field_validator

from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from powercontext.artifacts import MemoryCitation
    from powercontext.builtin.runtime.application import ScopedMemoryApplication


class _DocumentIdentity(BaseModel):
    document_id: str

    @field_validator("document_id")
    @classmethod
    def require_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be empty or whitespace")  # noqa: TRY003
        return value


class PDFDocumentInput(_DocumentIdentity):
    """An entire original PDF, identified by the caller."""

    content: bytes


class PDFPageInput(_DocumentIdentity):
    """Extracted text at one one-based physical location in an exact PDF revision."""

    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: StrictInt = Field(ge=1)
    text: str


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page, including blanks, or fail without partial output.

    Plain pypdf extraction retains the complete text and table numbers without
    inserting layout-dependent content. The digest always covers the original
    input bytes, including encryption and metadata, rather than a rewritten PDF.
    """

    from pypdf import PdfReader

    if not value.content or not value.content.lstrip().startswith(b"%PDF-"):
        raise ValueError("content must be a complete PDF")  # noqa: TRY003
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        # Strict parsing prevents a repaired/truncated document from silently
        # yielding only its readable prefix. Empty user-password permissions are
        # legal and must be decrypted before touching the page tree.
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a non-empty password")  # noqa: TRY003, TRY301
        count = len(reader.pages)
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=index + 1,
                text=reader.pages[index].extract_text() or "",
            )
            for index in range(count)
        )
    except Exception as error:
        raise ValueError("PDF could not be completely parsed") from error  # noqa: TRY003
    return pages


class PDFPageSource(Source):
    """Captured page value; later revisions never mutate this evidence."""

    page: PDFPageInput


class _PDFPageAdapter:
    input_class = PDFPageInput
    name = "pdf-page"
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        # Canonical tuple encoding avoids delimiter ambiguity and bounds names
        # even for long/unicode IDs. Never hash the text: identity is a location.
        identity = json.dumps(
            [value.document_id, value.document_sha256, value.page_number],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return PDFPageSource(
            name="pdf-page:" + hashlib.sha256(identity).hexdigest(),
            materialization=SourceMaterialization.CAPTURED,
            page=value.model_copy(deep=True),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return source.page.model_copy(deep=True)


class _PDFPageTextProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        page = source.page
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{page.document_id}\n{page.text}",
            metadata={
                "document_id": page.document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    _PDFPageAdapter(), version="1", projections=(_PDFPageTextProjection(),)
)


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Search an opened scope using only public Memory APIs and exact citations.

    A lexical search supplies candidates; the scope's active entries supply
    collection statistics and recover synonyms excluded by generic FTS admission.
    At the competition's scale (about a thousand pages), a transient full-scope
    rerank is inexpensive and avoids an external index or any stored side files.
    """

    from powercontext.builtin.runtime.models import SearchMemoryRequest
    from powercontext.sources._pdf_retrieval import rank_pages, search_terms

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")  # noqa: TRY003
    if limit <= 0 or not question.strip():
        return ()
    query = " ".join(search_terms(question))
    if not query:
        return ()
    hits = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(40, limit)))
    current = await memory.list()
    candidates = [
        record
        for record in current.entries
        if record.state == "active"
        and len(record.entry.sources) == 1
        and record.entry.sources[0].source_type == "pdf-page"
    ]
    return rank_pages(candidates, question, hits.hits, limit)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "parse_pdf_document",
    "search_pdf_pages",
]
