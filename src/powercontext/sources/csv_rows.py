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

"""CSV row Sources with stable identities and text-evidence projections."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceMaterialization,
    TextEvidence,
)

CSV_ROW_SOURCE_NAME = "csv-row"


class CSVDocumentInput(BaseModel):
    """An offline CSV document and the caller-selected record identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    primary_key: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("document_id must be non-empty without surrounding whitespace")  # noqa: TRY003
        return value

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, value: str) -> str:
        if not value:
            raise ValueError("primary_key must be non-empty")  # noqa: TRY003
        return value


class CSVRowInput(BaseModel):
    """One CSV record in the exact column order and string values supplied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("document_id must be non-empty without surrounding whitespace")  # noqa: TRY003
        return value

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, value: str) -> str:
        if not value:
            raise ValueError("primary_key must be non-empty")  # noqa: TRY003
        return value

    @field_validator("primary_key_value")
    @classmethod
    def validate_primary_key_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("primary_key_value must not be blank")  # noqa: TRY003
        return value

    @model_validator(mode="after")
    def validate_columns_and_values(self) -> CSVRowInput:
        if not self.columns:
            raise ValueError("columns must not be empty")  # noqa: TRY003
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("columns must be unique")  # noqa: TRY003
        if any(not column.strip() for column in self.columns):
            raise ValueError("columns must not be blank")  # noqa: TRY003
        if len(self.columns) != len(self.values):
            raise ValueError("columns and values must have the same length")  # noqa: TRY003
        if self.primary_key not in self.columns:
            raise ValueError("primary_key must exactly match a column")  # noqa: TRY003
        return self


class CSVRowSource(Source):
    """A captured Source representing one stable CSV record."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_source_identity(self) -> CSVRowSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the Source name")  # noqa: TRY003
        if self.source_id != csv_row_source_id(self.document_id, self.primary_key_value):
            raise ValueError("source_id must match the CSV row identity")  # noqa: TRY003
        return self


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Return the delimiter-safe, stable identity for one CSV row."""

    if not document_id or not isinstance(document_id, str) or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty without surrounding whitespace")  # noqa: TRY003
    if not isinstance(primary_key_value, str) or not primary_key_value.strip():
        raise ValueError("primary_key_value must not be blank")  # noqa: TRY003

    try:
        source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    except UnicodeEncodeError as error:
        raise ValueError("CSV row identity components must be valid UTF-8 text") from error  # noqa: TRY003
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"CSV row source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def _validate_header(header: list[str] | None, primary_key: str) -> tuple[str, ...]:
    if not header:
        raise ValueError("CSV header must not be empty")  # noqa: TRY003
    if any(not column.strip() for column in header):
        raise ValueError("CSV header columns must not be blank")  # noqa: TRY003
    if len(set(header)) != len(header):
        raise ValueError("CSV header columns must be unique")  # noqa: TRY003
    if primary_key not in header:
        raise ValueError("primary_key must exactly match a CSV header column")  # noqa: TRY003
    return tuple(header)


def _parse_row(
    record: list[str],
    *,
    columns: tuple[str, ...],
    primary_key_index: int,
    document_id: str,
    primary_key: str,
    seen_primary_keys: set[str],
) -> CSVRowInput:
    if len(record) != len(columns):
        raise ValueError("every CSV record must have the same number of fields as the header")  # noqa: TRY003

    primary_key_value = record[primary_key_index]
    if not primary_key_value.strip():
        raise ValueError("CSV primary key values must not be blank")  # noqa: TRY003
    if primary_key_value in seen_primary_keys:
        raise ValueError("CSV primary key values must be unique within a document")  # noqa: TRY003
    seen_primary_keys.add(primary_key_value)

    return CSVRowInput(
        document_id=document_id,
        primary_key=primary_key,
        primary_key_value=primary_key_value,
        columns=columns,
        values=tuple(record),
    )


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate every row before returning any CSV row input."""

    try:
        text = value.content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error  # noqa: TRY003

    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", quotechar='"', strict=True)
        header = next(reader, None)
        columns = _validate_header(header, value.primary_key)
        primary_key_index = columns.index(value.primary_key)
        seen_primary_keys: set[str] = set()
        rows: list[CSVRowInput] = []

        for record in reader:
            if not record:
                continue
            rows.append(
                _parse_row(
                    record,
                    columns=columns,
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_index=primary_key_index,
                    seen_primary_keys=seen_primary_keys,
                )
            )
    except csv.Error as error:
        raise ValueError("CSV content is malformed") from error  # noqa: TRY003

    return tuple(rows)


class CSVRowSourceAdapter:
    """Resolve and read captured CSV row Sources."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Expose one complete CSV record as canonical text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_ADAPTER = CSVRowSourceAdapter()
CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSV_ROW_SOURCE_ADAPTER,
    version="1",
    projections=(CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_ADAPTER",
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "CSVRowSourceAdapter",
    "CSVRowTextEvidenceProjection",
    "csv_row_source_id",
    "parse_csv_document",
]
