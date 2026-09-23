"""Agent 1 (Finder): read the document and extract values that answer the question.

The LLM only reads and records. It must copy an exact quote and name the element it
came from; the system fills in document, page and reliability tier itself.
"""
from __future__ import annotations

from .llm import LLMClient
from .schema import ElementType, FinderOutput, ParsedDocument

SYSTEM = """You extract epidemiological values from ONE research document for a public health scientist.

Rules:
- Use only the document below. Never use outside knowledge.
- For every value, give the element_id it came from and a quote copied EXACTLY from that element.
  For tables, copy the full row as written, including the " | " separators.
- Record values as printed. Do not calculate, convert or correct anything.
- If the paper gives the counts behind a rate (e.g. cases and population), record them as
  numerator and denominator.
- Match the question's scope (population, age group, period). If a value is for a different
  scope, still record it but state the actual population precisely.
- study_period is when the data was collected, not the publication year.
- If nothing in the document answers the question, return no answers and explain in not_found_reason.
- Figures marked "image content not read" contain only a caption; never infer values from them."""


def render(doc: ParsedDocument) -> str:
    parts = []
    for e in doc.elements:
        if e.type == ElementType.page_image:
            continue
        attrs = f'id="{e.id}" page="{e.page}" type="{e.type.value}" section="{e.section or ""}"'
        if e.note:
            attrs += f' note="{e.note}"'
        parts.append(f"<element {attrs}>\n{e.content}\n</element>")
    return "\n".join(parts)


class Finder:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def find(self, doc: ParsedDocument, question: str) -> FinderOutput:
        prompt = (
            f'<document name="{doc.document}">\n{render(doc)}\n</document>\n\n'
            f"Question: {question}"
        )
        return self.llm.extract(SYSTEM, prompt, FinderOutput)
