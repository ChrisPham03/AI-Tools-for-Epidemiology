"""Agent 3 (Reporter): attach sources, enforce "no source, no answer", and present.

Stage 1 grounding checks (plain code, no LLM):
- the cited element exists in the parsed document
- the quote actually appears in that element
Answers that fail are not shown as answers; they are listed as rejected with the reason.
Content checks (recomputing rates, comparing mentions) come in Stage 2 (Agent 2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Extraction, ExtractionDraft, FinderOutput, ParsedDocument, Source

UNREAD_NOTE = "image content not read"


def normalize(text: str) -> str:
    text = text.replace("|", " ").lower()
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Report:
    question: str
    document: str
    answers: list[Extraction] = field(default_factory=list)
    rejected: list[tuple[ExtractionDraft, str]] = field(default_factory=list)
    malformed: list[str] = field(default_factory=list)
    not_found_reason: str | None = None


def ground(doc: ParsedDocument, draft: ExtractionDraft) -> tuple[Extraction | None, str | None]:
    element = doc.get(draft.element_id)
    if element is None:
        return None, f"cited element '{draft.element_id}' does not exist"
    if element.note and UNREAD_NOTE in element.note:
        return None, f"'{element.id}' is an image that was not read; its values cannot be verified"
    if normalize(draft.quote) not in normalize(element.content):
        return None, f"quote not found in {element.id}"
    source = Source(
        document=doc.document, page=element.page, element_id=element.id,
        element_type=element.type, section=element.section, quote=draft.quote, tier=element.tier,
    )
    return Extraction(draft=draft, source=source), None


def build_report(doc: ParsedDocument, question: str, found: FinderOutput) -> Report:
    report = Report(question=question, document=doc.document, not_found_reason=found.not_found_reason,
                    malformed=[f"{a.raw.get('measure_as_reported', '?')}: {a.error}"
                               for a in found.invalid_answers])
    for draft in found.answers:
        extraction, problem = ground(doc, draft)
        if extraction:
            report.answers.append(extraction)
        else:
            report.rejected.append((draft, problem))
    return report


def _fmt_value(d: ExtractionDraft) -> str:
    if d.shape.value == "central_spread":
        main = f"median {d.median:g}" if d.median is not None else f"mean {d.mean:g}"
    else:
        main = f"{d.value:g}"
    unit = "%" if d.unit in ("%", "percent") else (f" {d.unit}" if d.unit else "")
    extra = ""
    if d.numerator is not None and d.denominator is not None:
        extra = f"  ({d.numerator:g} / {d.denominator:g})"
    if d.ci_low is not None and d.ci_high is not None:
        extra += f"  95% CI {d.ci_low:g}–{d.ci_high:g}"
    return main + unit + extra


def to_text(report: Report) -> str:
    out = [f"Question: {report.question}", f"Document: {report.document}", ""]
    shown = [x for x in report.answers if x.status != "excluded"]
    excluded = [x for x in report.answers if x.status == "excluded"]
    if report.answers:
        docs = {(x.source.document, x.source.element_id) for x in shown}
        line = f"{len(shown)} answer{'s' if len(shown) != 1 else ''} from {len(docs)} source{'s' if len(docs) != 1 else ''}."
        if excluded:
            line += f" {len(excluded)} excluded by you."
        out += [line, ""]
    if not report.answers and report.rejected:
        n = len(report.rejected)
        out.append(f"No verified answer. {n} candidate{'s' if n > 1 else ''} found, "
                   "but could not be matched to the source. Check manually.")
    elif not report.answers:
        out.append("NOT FOUND in this document.")
        if report.not_found_reason:
            out.append(f"  Reason: {report.not_found_reason}")
    for i, x in enumerate(shown, 1):
        d, s = x.draft, x.source
        mark = "  [accepted]" if x.status == "accepted" else ""
        out += [
            f"{i}. {d.measure_as_reported}: {_fmt_value(d)}{mark}",
            f"   Population: {d.population or '-'} | Location: {d.location or '-'} | Period: {d.study_period or '-'}",
            f"   Source: {s.document}, page {s.page}, {s.element_id} ({s.element_type.value}, "
            f"section: {s.section or '-'}, reliability tier {s.tier})",
            f'   Quote: "{s.quote}"',
            f"   Why: {d.reasoning}",
            "",
        ]
    if excluded:
        out.append("Excluded by you (undo in the app or outputs/decisions.json):")
        for x in excluded:
            out.append(f"  - {x.draft.measure_as_reported} = {_fmt_value(x.draft)} ({x.source.element_id})")
    if report.rejected:
        out.append("")
        out.append("Unverified candidates (not shown as answers):")
        for d, problem in report.rejected:
            out.append(f"  - {d.measure_as_reported} = {d.value} (cited {d.element_id}): {problem}")
            out.append(f'    Model\'s quote: "{d.quote}"')
    if report.malformed:
        out.append("")
        out.append("Model answers dropped because they broke the schema rules (see run log):")
        for m in report.malformed:
            out.append(f"  - {m}")
    return "\n".join(out)
