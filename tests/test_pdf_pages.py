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

"""Public-behavior regressions for complete PDF evidence and exact retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
from pathlib import Path
from typing import cast

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    MemoryEntryInput,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceMaterialization,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def _pdf(*texts: str, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
            })
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 10 Tf 20 700 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(user_password=password, owner_password="owner-password")  # noqa: S106
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_preserves_all_physical_pages_and_exact_original_digest() -> None:
    raw = _pdf("Revenue 1,234.50 Net income (123)", "", "Cash flows 987")
    pages = parse_pdf_document(PDFDocumentInput(document_id="Annual 2026", content=raw))
    assert [page.page_number for page in pages] == [1, 2, 3]
    assert pages[1].text == ""
    assert "1,234.50" in pages[0].text and "(123)" in pages[0].text
    assert "987" in pages[2].text
    assert all(page.document_sha256 == hashlib.sha256(raw).hexdigest() for page in pages)


@pytest.mark.parametrize("document_id", ["", " ", "\t\n"])
def test_rejects_blank_document_identity(document_id: str) -> None:
    with pytest.raises(ValueError):
        PDFDocumentInput(document_id=document_id, content=_pdf("a"))
    with pytest.raises(ValueError):
        PDFPageInput(document_id=document_id, document_sha256="a" * 64, page_number=1, text="a")


@pytest.mark.parametrize("raw", [b"", b"not a PDF", b"%PDF-1.7\ntruncated"])
def test_rejects_unreadable_input(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="invalid", content=raw))


def test_empty_password_permissions_and_required_password() -> None:
    pages = parse_pdf_document(PDFDocumentInput(document_id="permissions", content=_pdf("Revenue 123", password="")))
    assert len(pages) == 1 and "123" in pages[0].text
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="private", content=_pdf("Revenue 123", password="secret")))  # noqa: S106


def test_broken_later_page_does_not_return_readable_prefix() -> None:
    raw = _pdf("Readable first page", "Unreadable second page")
    # Keep the xref byte offsets unchanged but corrupt the second page's stream
    # reference. The first page stays fully readable.
    match = tuple(re.finditer(rb"/Contents (\d+) 0 R", raw))[-1]
    raw = raw[: match.start(1)] + b"0" * len(match[1]) + raw[match.end(1) :]
    assert b"/Contents 0 0 R" in raw
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="damaged", content=raw))


def test_identity_revision_projection_and_captured_value_are_stable() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        pages = parse_pdf_document(PDFDocumentInput(document_id="报告/alpha:" * 500, content=_pdf("Revenue 123", "")))
        sources = [await registry.resolve(page) for page in pages]
        assert len({source.name for source in sources}) == 2
        for page, source in zip(pages, sources, strict=True):
            assert len(source.name) <= 256
            assert source.materialization is SourceMaterialization.CAPTURED
            assert (await registry.resolve(page)).name == source.name
            assert await registry.read(source) == page
            projection = project_source_for_transport(registry, source).projection(TEXT_EVIDENCE_PROJECTION_KEY)
            assert projection == {
                "source_type": "pdf-page",
                "source_id": source.name,
                "content": f"{page.document_id}\n{page.text}",
                "metadata": {
                    "document_id": page.document_id,
                    "document_sha256": page.document_sha256,
                    "page_number": page.page_number,
                },
            }
        original = await registry.read(sources[0])
        assert isinstance(original, PDFPageInput)
        pages[0].text = "caller mutation"
        assert await registry.read(sources[0]) == original
        revision = original.model_copy(update={"document_sha256": "f" * 64})
        assert (await registry.resolve(revision)).name != sources[0].name
        different_id = original.model_copy(update={"document_id": "another document"})
        assert (await registry.resolve(different_id)).name != sources[0].name

    asyncio.run(scenario())


def test_search_real_scope_reopen_limit_deduplication_and_exact_readback(tmp_path: Path) -> None:
    async def scenario() -> None:
        class EvidencePipeline:
            async def extract(self, request, /) -> tuple[MemoryEntryInput, ...]:
                return tuple(
                    MemoryEntryInput(
                        kind="source-evidence",
                        text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                        sources=(source,),
                    )
                    for source in request.sources
                )

        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}"))
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        pages = parse_pdf_document(
            PDFDocumentInput(
                document_id="EXAMPLE_2026_10K",
                content=_pdf(
                    "Consolidated statements of income Revenue 820 Operating income 75",
                    "Consolidated statements of cash flows Depreciation 12 Capital expenditures 20",
                    "",
                ),
            )
        )
        observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="PDF", summary="Evidence", idempotency_key="pdf"))
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for observation in observations:
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
        async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            for _ in range(len(observations) + 1):
                if not (await memory.flush()).processed:
                    break
            else:
                raise AssertionError("flush did not drain the captured sources")  # noqa: TRY003
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            memory = runtime.memory.for_scope(scope.scope_id)
            for limit in [1, 2, 20]:
                citations = await search_pdf_pages(memory, "What is EBITDA based on income and cash flows?", limit)
                assert 0 < len(citations) <= min(limit, 2)
                sources = set()
                for citation in citations:
                    assert isinstance(citation, MemoryCitation)
                    record = await memory.get(GetMemoryEntryRequest(citation=citation))
                    assert record.citation == citation
                    source = record.entry.sources[0]
                    assert source.source_type == "pdf-page"
                    assert source.source_id not in sources
                    sources.add(source.source_id)
            assert await search_pdf_pages(memory, "", 20) == ()
            assert await search_pdf_pages(memory, "income", 0) == ()
            assert await search_pdf_pages(memory, "income", -1) == ()
            with pytest.raises(TypeError):
                await search_pdf_pages(memory, "income", cast(int, 1.5))
            empty = await runtime.scopes.create(ScopeDraft(title="Empty", summary="None", idempotency_key="empty"))
            assert await search_pdf_pages(runtime.memory.for_scope(empty.scope_id), "revenue", 20) == ()

    asyncio.run(scenario())
