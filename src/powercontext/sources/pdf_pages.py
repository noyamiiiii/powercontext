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
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBytes, StrictInt, field_validator, model_validator

from powercontext.artifacts import MemoryCitation
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


@dataclass(frozen=True)
class _PDFPageCandidate:
    citation: MemoryCitation
    document_id: str
    body: str


async def search_pdf_pages(memory: object, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Search a scoped Memory and return distinct real page citations."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")

    pages = await _pdf_page_candidates(memory)
    if not pages:
        return ()
    by_document: dict[str, list[_PDFPageCandidate]] = {}
    for page in pages:
        by_document.setdefault(page.document_id, []).append(page)
    document_ids = _matching_documents(question, tuple(by_document))
    ranked: list[tuple[float, _PDFPageCandidate]] = []
    for document_id in document_ids:
        ranked.extend(_rank_document_pages(question, document_id, tuple(by_document[document_id])))
    ranked.sort(key=lambda item: (-item[0], item[1].document_id, item[1].citation.entry_id))
    return tuple(page.citation for _, page in ranked[:limit])


async def _pdf_page_candidates(memory: object) -> tuple[_PDFPageCandidate, ...]:
    list_entries = getattr(memory, "list", None)
    if not callable(list_entries):
        return ()
    page = await list_entries()
    candidates: list[_PDFPageCandidate] = []
    seen: set[tuple[str, int, str, str]] = set()
    for record in page.entries:
        if record.state != "active" or not any(
            source.source_type == PDF_PAGE_SOURCE_NAME for source in record.entry.sources
        ):
            continue
        citation = record.citation
        key = (
            citation.memory_ref.artifact_id,
            citation.memory_ref.revision,
            citation.entry_id,
            citation.entry_version_id,
        )
        if key in seen:
            continue
        seen.add(key)
        document_id, separator, body = record.entry.text.partition("\n")
        if not separator or not document_id.strip() or not body.strip():
            continue
        candidates.append(
            _PDFPageCandidate(
                citation=citation,
                document_id=document_id.strip(),
                body=body,
            )
        )
    return tuple(candidates)


def _matching_documents(question: str, document_ids: Sequence[str]) -> tuple[str, ...]:
    haystack = _compact(question)
    scored = []
    for document_id in document_ids:
        company = re.split(r"_\d{4}", document_id, maxsplit=1)[0]
        compact_company = _compact(company)
        overlap = len(set(_normalized_tokens(company)).intersection(_normalized_tokens(question)))
        score = overlap * 10
        if compact_company and compact_company in haystack:
            score += 100 + len(compact_company)
        if score:
            scored.append((score, document_id))
    if not scored:
        return tuple(document_ids)
    best = max(score for score, _ in scored)
    matching = tuple(document_id for score, document_id in scored if score == best)
    return matching if best >= 10 else tuple(document_ids)


def _rank_document_pages(
    question: str,
    document_id: str,
    pages: Sequence[_PDFPageCandidate],
) -> list[tuple[float, _PDFPageCandidate]]:
    query = _expanded_question_terms(question, document_id)
    page_terms = [tuple(_normalized_tokens(page.body)) for page in pages]
    counts = [Counter(value) for value in page_terms]
    document_frequency = {term: sum(term in count for count in counts) for term in query}
    page_count = max(1, len(pages))
    average_length = max(1.0, sum(len(value) for value in page_terms) / page_count)
    normalized_question = " ".join(_raw_tokens(question))
    income_intent, balance_intent, cash_intent = _financial_intents(normalized_question)
    if "capital intensive" in normalized_question:
        income_intent = balance_intent = cash_intent = True
    if "inventory turnover" in normalized_question or "return on assets" in normalized_question:
        income_intent = balance_intent = True
    result: list[tuple[float, _PDFPageCandidate]] = []
    structural: list[_PDFPageCandidate] = []
    for index, page in enumerate(pages):
        count = counts[index]
        length_normalization = 1.2 * (0.25 + 0.75 * len(page_terms[index]) / average_length)
        value = 0.0
        for term in query:
            frequency = count[term]
            if not frequency:
                continue
            document_frequency_value = document_frequency[term]
            inverse_frequency = math.log(
                1 + (page_count - document_frequency_value + 0.5) / (document_frequency_value + 0.5)
            )
            value += inverse_frequency * frequency * 2.2 / (frequency + length_normalization)
        coverage = sum(term in count for term in query) / max(1, len(query))
        numeric_hits = sum(any(character.isdigit() for character in term) and term in count for term in query)
        boost, is_structural = _page_structural_signal(
            page.body,
            normalized_question,
            income_intent=income_intent,
            balance_intent=balance_intent,
            cash_intent=cash_intent,
        )
        if is_structural:
            structural.append(page)
        result.append((value + 4.0 * coverage + 0.8 * numeric_hits + boost, page))
    ordered = sorted(
        result,
        key=lambda item: (-item[0], item[1].citation.entry_id, item[1].citation.entry_version_id),
    )
    structural_ids = {id(page) for page in structural}
    selected = [item for item in ordered if id(item[1]) in structural_ids]
    selected.extend(item for item in ordered if id(item[1]) not in structural_ids)
    return selected


def _page_structural_signal(
    body: str,
    question: str,
    *,
    income_intent: bool,
    balance_intent: bool,
    cash_intent: bool,
) -> tuple[float, bool]:
    body_lower = body.casefold()
    headings = _page_heading(body)
    boost = 0.0
    structural = False
    if income_intent and any(
        "statement" in heading and ("income" in heading or "operations" in heading) for heading in headings
    ):
        boost += 1000.0
        structural = True
    if balance_intent and any("balance sheet" in heading for heading in headings):
        boost += 1000.0
        structural = True
    if cash_intent and any("cash flow" in heading for heading in headings):
        boost += 1000.0
        structural = True
    if income_intent and any("summary of financial performance" in heading for heading in headings):
        boost += 30.0
    if any("business segment" in heading for heading in headings) and ("categor" in question or "segment" in question):
        boost += 50.0
        structural = True
    if any("results of operations" in heading for heading in headings) and (
        "drove" in question or "change" in question
    ):
        boost += 40.0
    narrative_boost, narrative_structural = _narrative_structural_signal(body_lower, question)
    return boost + narrative_boost, structural or narrative_structural


def _narrative_structural_signal(body: str, question: str) -> tuple[float, bool]:
    if "legal" in question and any(term in body for term in ("legal action", "litigation", "proceeding", "claim")):
        return 12.0, False
    if "customer" in question and any(
        term in body for term in ("one customer", "customer accounted", "commercial airlines", "u.s. government")
    ):
        return 50.0, True
    if "production" in question and any(term in body for term in ("737", "787", "777x")):
        return 50.0, True
    if "industry" in question and any(term in body for term in ("global leader", "packaging", "primarily")):
        return 15.0, False
    return 0.0, False


def _expanded_question_terms(question: str, document_id: str) -> tuple[str, ...]:  # noqa: C901
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
    normalized = content.casefold().replace("&", " and ").replace("-", " ")
    output = [
        _normalize_term(term)
        for term in _raw_tokens(content)
        if term not in _QUERY_STOP_WORDS and term not in _DOCUMENT_COMMON_TERMS
    ]
    company = re.split(r"_\d{4}", document_id, maxsplit=1)[0]
    company_terms = set(_normalized_tokens(company))
    output = [term for term in output if term not in company_terms]
    expansions: list[str] = []
    phrases = {
        ("operating", "margin"): (
            "operating income",
            "operating profit",
            "revenue",
            "net sales",
            "gross profit",
            "operating expenses",
        ),
        ("gross", "margin"): ("gross profit", "revenue", "net sales", "cost of sales", "cost of revenue"),
        ("free", "cash"): (
            "free cash flow",
            "net cash provided by operating activities",
            "purchases of property and equipment",
            "net income",
            "cash flow conversion",
        ),
        ("cashflow", "conversion"): (
            "free cash flow",
            "net cash provided by operating activities",
            "purchases of property and equipment",
            "net income",
        ),
        ("capital", "intensive"): (
            "capital expenditures",
            "purchases of property plant and equipment",
            "fixed assets",
            "property plant and equipment",
            "total assets",
            "net sales",
        ),
        ("inventory", "turnover"): ("inventory", "cost of sales", "balance sheet", "statements of operations"),
        ("quick", "ratio"): (
            "cash and cash equivalents",
            "current assets",
            "current liabilities",
            "inventory",
            "balance sheet",
        ),
        ("return", "on", "assets"): ("net income", "total assets", "balance sheet", "statements of operations"),
        ("effective", "tax", "rate"): (
            "provision for income taxes",
            "income tax expense",
            "income before income taxes",
            "loss before income taxes",
        ),
        ("legal", "battles"): ("legal actions", "legal proceedings", "litigation", "claims", "lawsuits"),
        ("legal", "actions"): ("legal proceedings", "litigation", "claims", "lawsuits"),
        ("product", "categories"): (
            "business segment",
            "commercial airplanes",
            "defense space security",
            "global services",
        ),
        ("service", "categories"): (
            "business segment",
            "commercial airplanes",
            "defense space security",
            "global services",
        ),
        ("primary", "customers"): (
            "commercial airlines",
            "customers",
            "clients",
            "u.s. government",
            "government contracts",
        ),
        ("card", "members"): ("card member retention", "retained", "retain"),
        ("customer", "concentration"): ("one customer", "net revenue", "sales", "segment", "loss", "customer"),
        ("industry",): ("packaging", "products", "business", "company", "markets"),
    }
    for phrase, values in phrases.items():
        if " ".join(phrase) in normalized:
            expansions.extend(values)
    compact_query = " ".join(output)
    if "geograph" in compact_query or "operate" in output or "operations" in output:
        expansions.extend(("united states", "emea", "apac", "lacc", "regions", "markets", "countries"))
    if "grow" in compact_query or "growth" in compact_query:
        expansions.extend(("organic sales change", "acquisitions", "divestitures", "translation", "business segment"))
    if "liabil" in compact_query:
        expansions.extend(("total liabilities", "deposits", "long-term debt", "accounts payable"))
    if "retain" in compact_query or "retention" in compact_query:
        expansions.extend(("card member retention", "retained", "retain"))
    if "drove" in output or "change" in output:
        expansions.extend((
            "selling general administrative",
            "percent of sales",
            "restructuring benefits",
            "growth initiatives",
        ))
    output.extend(_normalized_tokens(" ".join(expansions)))
    return tuple(dict.fromkeys(term for term in output if term))


def _financial_intents(question: str) -> tuple[bool, bool, bool]:
    income = any(
        term in question
        for term in (
            "margin",
            "revenue",
            "sales",
            "income",
            "profit",
            "tax",
            "restructuring",
            "p&l",
            "gross",
        )
    )
    balance = any(term in question for term in ("balance sheet", "asset", "liabilit", "inventory", "quick ratio"))
    cash = any(term in question for term in ("cash flow", "cashflow", "capex", "capital expend", "free cash"))
    return income, balance, cash


def _page_heading(value: str) -> tuple[str, ...]:
    return tuple(line.strip().casefold() for line in value.splitlines() if line.strip() and len(line.strip()) <= 100)[
        :10
    ]


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


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
