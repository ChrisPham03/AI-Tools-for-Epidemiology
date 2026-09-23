"""Data model.

Two kinds of structures live here:
- Element: a piece of a parsed document (paragraph, table, figure) with its location.
- Extraction: one value pulled from a document, with its source.

The extraction schema is shape-based: disease and measure names are data, and the
shape decides which numeric fields are expected. Source fields are always required.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------- documents

class ElementType(str, Enum):
    text = "text"
    table = "table"
    figure = "figure"
    page_image = "page_image"  # scanned page with no text layer


# How much we trust that the content was READ correctly (not that the paper is right).
TIER_BY_TYPE = {
    ElementType.table: 1,       # digital table
    ElementType.text: 2,        # digital text
    ElementType.page_image: 3,  # needs OCR
    ElementType.figure: 4,      # values in images are estimates
}


class Element(BaseModel):
    id: str                          # e.g. "p3-table1"
    document: str                    # file name, e.g. "3.pdf"
    page: int                        # 1-based PDF page index
    type: ElementType
    section: Optional[str] = None    # nearest heading, e.g. "Results"
    content: str                     # text; table rows use " | " between cells
    bbox: tuple[float, float, float, float]  # x0, top, x1, bottom in PDF points
    tier: int
    note: Optional[str] = None       # e.g. "image content not read"


class ParsedDocument(BaseModel):
    document: str
    pages: int
    elements: list[Element]

    def get(self, element_id: str) -> Optional[Element]:
        return next((e for e in self.elements if e.id == element_id), None)


# ------------------------------------------------------------- extractions

class Shape(str, Enum):
    proportion = "proportion"          # attack rate, CFR, coverage ...
    central_spread = "central_spread"  # incubation period, serial interval ...
    ratio = "ratio"                    # vaccine efficacy, odds ratio, RR ...
    count = "count"                    # cases, deaths ...
    estimate = "estimate"              # R0, growth rate ...


class ExtractionDraft(BaseModel):
    """What the LLM fills in. The system adds document, page and tier itself."""

    disease: str
    measure_as_reported: str = Field(description="Measure name exactly as the paper words it")
    measure_normalized: Optional[str] = Field(
        None, description="Standard short name (e.g. CFR, attack_rate). Leave null if unsure."
    )
    shape: Shape

    value: Optional[float] = Field(None, description="Main reported value, as printed")
    unit: Optional[str] = None
    numerator: Optional[float] = Field(None, description="Count on top, if the paper gives it")
    denominator: Optional[float] = Field(None, description="Count underneath, if the paper gives it")
    mean: Optional[float] = None
    median: Optional[float] = None
    sd: Optional[float] = None
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None

    population: Optional[str] = Field(None, description="Who the value applies to, e.g. 'children under 5'")
    location: Optional[str] = None
    study_period: Optional[str] = Field(None, description="When the data was collected, not publication date")

    element_id: str = Field(description="ID of the element the value was read from")
    quote: str = Field(min_length=1, description="Exact text copied from that element")
    reasoning: str = Field(description="Where and why: e.g. 'Table 2, row Total, column CFR'")

    @model_validator(mode="after")
    def _shape_has_a_value(self):
        if self.shape == Shape.central_spread:
            ok = self.mean is not None or self.median is not None
        else:
            ok = self.value is not None
        if not ok:
            raise ValueError(f"shape '{self.shape.value}' is missing its main value")
        return self


class FinderOutput(BaseModel):
    answers: list[ExtractionDraft] = Field(default_factory=list)
    not_found_reason: Optional[str] = Field(
        None, description="If nothing in the document answers the question, say why"
    )


class Source(BaseModel):
    document: str
    page: int
    element_id: str
    element_type: ElementType
    section: Optional[str]
    quote: str
    tier: int


Status = Literal["pending", "accepted", "needs_review", "excluded"]


class Extraction(BaseModel):
    """A draft plus the system-filled source, flags and review status."""

    draft: ExtractionDraft
    source: Source
    flags: list[str] = Field(default_factory=list)
    status: Status = "pending"
