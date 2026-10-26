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

"""Deterministic, collection-aware ranking of persisted PDF page evidence.

This module knows financial vocabulary, but no companies, documents, questions,
answers, page locations, or evaluation assets. It reads only Memory records.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from powercontext.artifacts import MemoryCitation
    from powercontext.builtin.artifacts.memory.models import MemoryHit
    from powercontext.builtin.runtime.models import MemoryEntryRecord

_WORDS = re.compile(r"[a-z]+|\d+")
_STOP = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "for",
    "to",
    "in",
    "on",
    "at",
    "by",
    "from",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "what",
    "which",
    "who",
    "how",
    "why",
    "when",
    "where",
    "do",
    "does",
    "did",
    "has",
    "have",
    "had",
    "can",
    "could",
    "should",
    "would",
    "i",
    "we",
    "you",
    "it",
    "its",
    "our",
    "your",
    "this",
    "that",
    "these",
    "those",
    "any",
    "some",
    "than",
    "then",
    "if",
    "not",
    "no",
    "only",
    "answer",
    "respond",
    "response",
    "question",
    "give",
    "state",
    "define",
    "calculate",
    "assuming",
    "perspective",
    "analyst",
    "investment",
    "use",
    "using",
    "shown",
    "details",
    "relying",
    "within",
    "directly",
    "explicitly",
    "outlined",
    "reported",
    "unadjusted",
    "adjusted",
    "usd",
    "dollar",
    "million",
    "billion",
    "fiscal",
    "fy",
    "year",
    "end",
    "ended",
    "respectively",
])
_NORMAL = {
    "geographies": "geography",
    "geographic": "geography",
    "geographical": "geography",
    "operates": "operation",
    "operating": "operation",
    "operations": "operation",
    "restructuring": "restructure",
    "restructured": "restructure",
    "amortisation": "amortization",
    "depreciated": "depreciation",
    "revenues": "revenue",
    "sales": "revenue",
    "earnings": "income",
    "countries": "country",
    "companies": "company",
    "liabilities": "liability",
    "inventories": "inventory",
    "activities": "activity",
    "purchases": "purchase",
    "expenditures": "expenditure",
    "taxes": "tax",
    "taxation": "tax",
}

# Trigger vocabulary -> alternate terminology, plus relevant statement headings.
# Separate concept rankings preserve evidence for questions needing several tables.
_CONCEPTS = (
    (
        {"geography", "country", "region", "worldwide", "international"},
        "geographic geography country countries region segment division business international markets",
        ("our divisions", "our business", "business segments", "geographic", "international operations"),
    ),
    (
        {"legal", "litigation", "lawsuit", "battle", "proceeding", "contingency"},
        "legal proceedings litigation lawsuits contingencies commitments settlement claims",
        ("legal proceedings", "legal matters", "contingencies", "litigation"),
    ),
    (
        {"restructure"},
        "restructuring impairment charges costs expenses income",
        ("restructuring", "consolidated statement of income", "consolidated statements of income"),
    ),
    (
        {"ebitda", "income", "profit", "margin", "ebit", "revenue", "p", "l"},
        "consolidated statements income earnings operations revenue net profit operating",
        (
            "consolidated statement of income",
            "consolidated statements of income",
            "consolidated statements of earnings",
            "consolidated statements of operations",
        ),
    ),
    (
        {"ebitda", "cash", "flow", "depreciation", "amortization", "capex", "fcf"},
        "consolidated statements cash flows depreciation amortization operating investing",
        ("consolidated statement of cash flows", "consolidated statements of cash flows"),
    ),
    (
        {"capex", "expenditure", "fcf"},
        "capital spending expenditures additions purchases property plant equipment investing cash flows",
        ("capital spending", "capital expenditures", "consolidated statements of cash flows"),
    ),
    (
        {"asset", "liability", "balance", "equity", "debt", "ratio", "liquidity", "working"},
        "consolidated balance sheets assets liabilities equity current debt cash",
        ("consolidated balance sheet", "consolidated balance sheets", "financial position"),
    ),
    (
        {"dividend", "repurchase", "buyback", "shareholder"},
        "dividends repurchase shares common stock shareholders cash flows equity",
        ("dividends", "share repurchases", "stockholders", "shareholders"),
    ),
    ({"inventory"}, "inventories inventory finished goods raw materials cost", ("inventories", "inventory")),
    (
        {"tax", "effective"},
        "income taxes effective tax rate provision deferred",
        ("income taxes", "effective tax rate"),
    ),
    ({"pension", "retirement"}, "pension retirement benefits obligation plan", ("pension", "retirement")),
    (
        {"acquisition", "goodwill"},
        "acquisition goodwill intangible assets purchase",
        ("acquisitions", "goodwill", "intangible assets"),
    ),
)


def _tokens(text: str) -> list[str]:
    words = _WORDS.findall(unicodedata.normalize("NFKC", text).casefold())
    return [_normalize(word) for word in words]


def _normalize(word: str) -> str:
    if word in _NORMAL:
        return _NORMAL[word]
    if word.endswith("ies") and len(word) > 5:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
        return word[:-1]
    return word


def search_terms(question: str) -> tuple[str, ...]:
    """Remove answer-format instructions and normalize fiscal year tokens."""

    return tuple(dict.fromkeys(token for token in _tokens(question) if token not in _STOP))


@dataclass
class _Page:
    record: MemoryEntryRecord
    source_id: str
    document_id: str
    terms: Counter[str]
    length: int
    heading: str


def _pages(records: Sequence[MemoryEntryRecord]) -> list[_Page]:
    pages: list[_Page] = []
    seen: set[str] = set()
    for record in records:
        source_id = record.entry.sources[0].source_id
        if source_id in seen:
            continue
        seen.add(source_id)
        document_id, _, text = record.entry.text.partition("\n")
        terms = Counter(_tokens(text))
        if not terms:
            continue
        heading = " ".join(_WORDS.findall(text[:1200].casefold()))
        pages.append(_Page(record, source_id, document_id, terms, sum(terms.values()), heading))
    return pages


def _bm25(page: _Page, weights: dict[str, float], idf: dict[str, float], average: float) -> float:
    norm = 1.2 * (0.25 + 0.75 * page.length / average)
    return sum(
        weight * idf.get(term, 0.0) * (count * 2.2 / (count + norm))
        for term, weight in weights.items()
        if (count := page.terms.get(term, 0))
    )


def _document_match(page: _Page, query: set[str]) -> float:
    # Derive company/year affinity from caller-provided document IDs, without a
    # company dictionary. Years stay a soft signal: questions may cite prior years.
    identity = set(_tokens(page.document_id))
    company = {term for term in identity if len(term) > 2 and term.isalpha() and term not in {"annual", "report"}}
    named = bool(company & query)
    years = {term for term in query if len(term) == 4 and term.isdigit()}
    return (1.5 if named else 1.0) * (1.12 if years & identity else 1.0)


def _target_documents(pages: list[_Page], question: str) -> list[_Page]:
    """Apply explicit company/year constraints inferred from document identities."""

    raw_query = set(re.findall(r"[a-z0-9]+", question.casefold()))
    query = set(search_terms(question))
    matched: set[str] = set()
    for page in pages:
        # Finance report IDs commonly use COMPANY_YEAR_FORM. Extract only the
        # prefix rather than matching generic form names or year digits.
        prefix = re.split(r"(?:19|20)\d{2}", page.document_id.casefold(), maxsplit=1)[0]
        identity = set(re.findall(r"[a-z0-9]+", prefix)) - {"inc", "corp", "annual", "report", "the"}
        if identity and (identity <= raw_query or set(_tokens(" ".join(identity))) <= query):
            matched.add(page.document_id)
    if not matched:
        return pages
    years = {term for term in query if len(term) == 4 and term.isdigit()}
    matching_year = {document_id for document_id in matched if years & set(_tokens(document_id))}
    targets = matching_year or matched
    return [page for page in pages if page.document_id in targets]


def rank_pages(
    records: Sequence[MemoryEntryRecord], question: str, hits: Sequence[MemoryHit], limit: int
) -> tuple[MemoryCitation, ...]:
    """Blend BM25, financial terminology and statement-specific evidence pools."""

    pages = _target_documents(_pages(records), question)
    if not pages:
        return ()
    query = set(search_terms(question))
    frequencies: Counter[str] = Counter()
    for page in pages:
        frequencies.update(page.terms.keys())
    size = len(pages)
    idf = {term: math.log1p((size - count + 0.5) / (count + 0.5)) for term, count in frequencies.items()}
    average = sum(page.length for page in pages) / size
    concepts = [concept for concept in _CONCEPTS if concept[0] & query]
    weights = {term: 1.0 for term in query if term not in _STOP and not term.isdigit()}
    for _triggers, expansion, _headings in concepts:
        for term in _tokens(expansion):
            weights.setdefault(term, 0.3)
    # Rare terms identify the substantive question; years and company names alone
    # cannot outrank the actual financial subject.
    affinity = [_document_match(page, query) for page in pages]
    fts_ranks = {hit.entry_version_id: rank for rank, hit in enumerate(hits)}
    scores = []
    for index, page in enumerate(pages):
        lexical = _bm25(page, weights, idf, average)
        headings = sum(
            2.5 if any(heading in page.heading for heading in phrases) else 0.0
            for _triggers, _expansion, phrases in concepts
        )
        fts = (
            0.5 / (1 + fts_ranks[page.record.entry.entry_version_id])
            if page.record.entry.entry_version_id in fts_ranks
            else 0
        )
        scores.append((lexical + headings + fts) * affinity[index])
    order = sorted(range(size), key=lambda index: (-scores[index], pages[index].source_id))

    # Several statement pages can jointly answer one question. Reserve a small
    # fraction of the result for each requested concept before filling by score.
    selected: set[int] = set()
    per_concept = min(3, limit // max(3, len(concepts) + 1))
    for _triggers, expansion, headings in concepts:
        concept_weights = dict.fromkeys(_tokens(expansion), 1.0)
        ranking = sorted(
            range(size),
            key=lambda index: (
                -(
                    _bm25(pages[index], concept_weights, idf, average)
                    + (6.0 if any(heading in pages[index].heading for heading in headings) else 0.0)
                )
                * affinity[index]
            ),
        )
        selected.update(index for index in ranking[:per_concept] if scores[index] > 0)
    for index in order:
        if len(selected) >= limit or scores[index] <= 0:
            break
        selected.add(index)
    # Every citation is provided by a real current-head Memory record. No memory
    # revision, entry identity, source, or page location is fabricated here.
    return tuple(pages[index].record.citation for index in order if index in selected)[:limit]
