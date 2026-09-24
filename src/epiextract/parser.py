"""PDF parsing: turn a PDF into Elements (paragraphs, tables, figures) with locations.

`DocumentParser` is the interface the rest of the pipeline depends on.
`PdfPlumberParser` is a local implementation for digital PDFs. It is tuned to
common two-column journal layouts (e.g. tables drawn with three horizontal rules).
A cloud parser (Amazon Textract, or Azure Document Intelligence in production)
can replace it without changing anything downstream.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

import pdfplumber

from .schema import TIER_BY_TYPE, Element, ElementType, ParsedDocument


class DocumentParser(ABC):
    @abstractmethod
    def parse(self, pdf_path: str | Path) -> ParsedDocument: ...


# ------------------------------------------------------------------ helpers

LIGATURE_BREAK = re.compile(r"\b(\w*?)(fi|fl|ff) (?=[a-z])")
TABLE_CAPTION = re.compile(r"^Table\s+(\d+)\s*[:.]")
FIGURE_CAPTION = re.compile(r"^Figure\s+(\d+)\s*[:.]")

HEADER_BOTTOM = 50    # running header area (points from top)
FOOTER_TOP = 740      # running footer area
LINE_TOLERANCE = 3    # words within this many points share a line
PARAGRAPH_GAP = 6     # vertical gap that starts a new paragraph
CELL_GAP = 7          # horizontal gap that separates table cells
HEADING_SIZE = 11.5   # font size at or above which a line is a heading


def fix_ligatures(text: str) -> str:
    """Repair words split at ligatures by the PDF, e.g. 'signifi cant' -> 'significant'."""
    return LIGATURE_BREAK.sub(lambda m: m.group(1) + m.group(2), text)


def group_lines(words: list[dict]) -> list[list[dict]]:
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    for w in words:
        if lines and abs(lines[-1][0]["top"] - w["top"]) < LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def line_text(line: list[dict], cell_sep: bool = False) -> str:
    text = line[0]["text"]
    for a, b in zip(line, line[1:]):
        gap = b["x0"] - a["x1"]
        text += (" | " if cell_sep and gap > CELL_GAP else " ") + b["text"]
    return text


def table_text(words: list[dict], body_bottom: float | None) -> str:
    """Render table rows as 'cell | cell | cell'.

    A long cell can wrap onto the next line, e.g.
        Among children aged less than | (32,774) | 794 | 24.2
        5 years
    A line inside the table body that holds only one cell is glued back onto the
    cell above it whose column it falls under. Lines below the table's last rule
    (footnotes) are never merged.
    """
    rows: list[list[list]] = []  # row -> cells -> [x0, x1, text]
    for line in group_lines(words):
        cells: list[list] = []
        for w in line:
            if cells and w["x0"] - cells[-1][1] <= CELL_GAP:
                cells[-1][1] = w["x1"]
                cells[-1][2] += " " + w["text"]
            else:
                cells.append([w["x0"], w["x1"], w["text"]])
        in_body = body_bottom is not None and line[0]["top"] < body_bottom
        if in_body and len(cells) == 1 and rows and len(rows[-1]) > 1:
            x0, x1, text = cells[0]
            # attach to the cell above that overlaps it most; if none overlap, the nearest one
            overlap = lambda c: min(c[1], x1) - max(c[0], x0)
            distance = lambda c: abs((c[0] + c[1]) / 2 - (x0 + x1) / 2)
            target = max(rows[-1], key=lambda c: (overlap(c), -distance(c)))
            target[2] += " " + text
        else:
            rows.append(cells)
    return "\n".join(" | ".join(c[2] for c in row) for row in rows)


def bbox_of(items: list[dict]) -> tuple[float, float, float, float]:
    return (
        round(min(i["x0"] for i in items), 1),
        round(min(i["top"] for i in items), 1),
        round(max(i["x1"] for i in items), 1),
        round(max(i["bottom"] for i in items), 1),
    )


def inside(word: dict, box: tuple[float, float, float, float]) -> bool:
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    return box[0] - 1 <= cx <= box[2] + 1 and box[1] - 1 <= cy <= box[3] + 1


# ------------------------------------------------------------------- parser

class PdfPlumberParser(DocumentParser):
    def parse(self, pdf_path: str | Path) -> ParsedDocument:
        pdf_path = Path(pdf_path)
        doc = pdf_path.name
        elements: list[Element] = []
        section = None

        with pdfplumber.open(pdf_path) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(extra_attrs=["size"])
                if len(words) < 20 and page.images:
                    elements.append(self._scanned_page(doc, page_no, page))
                    continue

                words = [w for w in words if HEADER_BOTTOM <= w["top"] <= FOOTER_TOP]
                gutter = page.width / 2
                regions, region_elements = self._tables_and_figures(doc, page_no, page, words, gutter)

                flow = [w for w in words if not any(inside(w, r) for r in regions)]
                start_section = section
                text_elements, section = self._paragraphs(doc, page_no, flow, gutter, section)
                for el in region_elements:
                    same_col = [t for t in text_elements
                                if (t.bbox[0] < gutter) == (el.bbox[0] < gutter) and t.bbox[1] < el.bbox[1]]
                    el.section = max(same_col, key=lambda t: t.bbox[1]).section if same_col else start_section
                elements += text_elements + region_elements

        return ParsedDocument(document=doc, pages=page_no, elements=elements)

    # ---- tables and figures -------------------------------------------------

    def _tables_and_figures(self, doc, page_no, page, words, gutter):
        regions, out = [], []
        rules = sorted(
            [l for l in page.lines if abs(l["top"] - l["bottom"]) < 1.5 and l["x1"] - l["x0"] > 100],
            key=lambda l: l["top"],
        )
        columns = [(0, gutter), (gutter, page.width)]
        lines = [
            (col, line)
            for col in columns
            for line in group_lines([w for w in words if col[0] <= w["x0"] < col[1]])
        ]

        for col, line in lines:
            text = line_text(line)

            if m := TABLE_CAPTION.match(text):
                below = [r for r in rules if r["top"] > line[0]["top"] and col[0] <= r["x0"] < col[1]]
                below = [r for r in below if r["top"] - line[0]["top"] < 300][:3]
                note, body_bottom = None, None
                if len(below) == 3:
                    bottom = body_bottom = below[-1]["top"]
                    # include a footnote line directly under the table (e.g. "CFR = ...")
                    foot = [w for w in words if col[0] <= w["x0"] < col[1] and 0 < w["top"] - bottom < 14]
                    if foot:
                        bottom = max(w["bottom"] for w in foot)
                else:
                    bottom = line[0]["bottom"]
                    note = "table boundary not detected; caption only"
                box = (col[0], line[0]["top"], col[1], bottom)
                regions.append(box)
                table_words = [w for w in words if inside(w, box)]
                content = fix_ligatures(table_text(table_words, body_bottom))
                out.append(self._element(doc, page_no, f"table{m.group(1)}", ElementType.table,
                                         content, bbox_of(table_words), note=note))

        for i, img in enumerate(page.images, start=1):
            caption = next(
                (l for _, l in lines
                 if FIGURE_CAPTION.match(line_text(l))
                 and -5 <= l[0]["top"] - img["bottom"] <= 30
                 and l[0]["x0"] < img["x1"] and l[-1]["x1"] > img["x0"]),
                None,
            )
            items = [img] + (caption or [])
            box = bbox_of(items)
            regions.append(box)
            if caption:
                num = FIGURE_CAPTION.match(line_text(caption)).group(1)
                eid, content = f"figure{num}", fix_ligatures(line_text(caption))
            else:
                eid, content = f"image{i}", "(unlabelled image)"
            out.append(self._element(doc, page_no, eid, ElementType.figure, content, box,
                                     note="image content not read; caption only"))
        return regions, out

    # ---- paragraphs ---------------------------------------------------------

    def _paragraphs(self, doc, page_no, words, gutter, section):
        """Reading order: full-width bands in place, two-column bands left then right."""
        out: list[Element] = []
        page_lines = group_lines(words)

        # split each page line into full-width, or left/right parts
        runs: list[tuple[str, list[list[dict]]]] = []
        for line in page_lines:
            if any(w["x0"] < gutter < w["x1"] for w in line):
                kind, parts = "full", [line]
            else:
                left = [w for w in line if w["x1"] <= gutter]
                right = [w for w in line if w["x0"] >= gutter]
                kind, parts = "cols", [p for p in (left, right) if p]
            if runs and runs[-1][0] == kind:
                runs[-1][1].extend(parts)
            else:
                runs.append((kind, list(parts)))

        ordered: list[list[dict]] = []
        for kind, parts in runs:
            if kind == "full":
                ordered += parts
            else:
                ordered += [p for p in parts if p[0]["x0"] < gutter]
                ordered += [p for p in parts if p[0]["x0"] >= gutter]

        para: list[list[dict]] = []
        counter = 0

        def flush():
            nonlocal para, counter
            if para:
                counter += 1
                text = fix_ligatures(" ".join(line_text(l) for l in para))
                # join words hyphenated across lines; letters only, so "2828- 1478" keeps its minus sign
                text = re.sub(r"([a-z])- ([a-z])", r"\1\2", text)
                out.append(self._element(doc, page_no, f"text{counter}", ElementType.text,
                                         text, bbox_of([w for l in para for w in l]), section=section))
                para = []

        prev = None
        prev_was_heading = False
        for line in ordered:
            is_heading = max(w["size"] for w in line) >= HEADING_SIZE
            if is_heading:
                flush()
                heading = fix_ligatures(line_text(line))
                section = f"{section} {heading}" if prev_was_heading else heading
                prev, prev_was_heading = None, True
                continue
            prev_was_heading = False
            new_column = prev is not None and abs(line[0]["x0"] - prev[0]["x0"]) > gutter / 2
            gap = line[0]["top"] - prev[0]["bottom"] if prev else 0
            if prev is not None and (gap > PARAGRAPH_GAP or gap < -LINE_TOLERANCE or new_column):
                flush()
            para.append(line)
            prev = line
        flush()
        return out, section

    # ---- misc ---------------------------------------------------------------

    def _scanned_page(self, doc, page_no, page):
        return self._element(doc, page_no, "page", ElementType.page_image, "",
                             (0, 0, page.width, page.height),
                             note="no text layer; OCR required (planned: Textract)")

    @staticmethod
    def _element(doc, page_no, local_id, etype, content, bbox, section=None, note=None):
        return Element(
            id=f"p{page_no}-{local_id}", document=doc, page=page_no, type=etype,
            section=section, content=content, bbox=bbox, tier=TIER_BY_TYPE[etype], note=note,
        )
