"""Render the cited region of a PDF page, highlighted, so a scientist can check it by eye."""
from __future__ import annotations

from pathlib import Path

import pdfplumber
from PIL import Image

HIGHLIGHT_FILL = (255, 196, 0, 70)
HIGHLIGHT_STROKE = (183, 121, 31)


def page_region(pdf_path: str | Path, page: int, bbox: tuple[float, float, float, float],
                margin: float = 40, resolution: int = 130, full_page: bool = False) -> Image.Image:
    """The cited element highlighted.

    By default the image is cropped to the element plus some surrounding context, so the
    value is easy to find. With full_page=True the whole page is shown, still highlighted.
    """
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[page - 1]
        if full_page:
            area = p
        else:
            x0, top, x1, bottom = bbox
            area = p.crop((
                max(0, x0 - margin), max(0, top - margin),
                min(p.width, x1 + margin), min(p.height, bottom + margin),
            ))
        image = area.to_image(resolution=resolution if not full_page else 100)
        image.draw_rect(bbox, fill=HIGHLIGHT_FILL, stroke=HIGHLIGHT_STROKE, stroke_width=2 if not full_page else 3)
        return image.annotated.copy()