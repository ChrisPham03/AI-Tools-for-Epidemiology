"""Command line entry point.

  python -m epiextract.cli parse data/3.pdf
  python -m epiextract.cli ask data/3.pdf "What was the case fatality rate?"
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .decisions import DecisionStore
from .finder import Finder
from .llm import default_client
from .parser import PdfPlumberParser
from .reporter import build_report, to_text
from .schema import ParsedDocument

OUTPUTS = Path("outputs")


def parse_cmd(pdf: Path) -> ParsedDocument:
    """Parse a PDF and save the extracted element structure to disk.

    Args:
        pdf: The PDF to parse.

    Returns:
        ParsedDocument: The parsed document object used by downstream analysis.
    """
    doc = PdfPlumberParser().parse(pdf)
    OUTPUTS.mkdir(exist_ok=True)
    out = OUTPUTS / f"{pdf.stem}.elements.json"
    out.write_text(doc.model_dump_json(indent=2))
    counts: dict[str, int] = {}
    for e in doc.elements:
        counts[e.type.value] = counts.get(e.type.value, 0) + 1
    print(f"Parsed {doc.document}: {doc.pages} pages, {len(doc.elements)} elements {counts}")
    print(f"Saved to {out}")
    return doc


def ask_cmd(pdf: Path, question: str) -> None:
    """Parse a document, ask a question, and print the grounded answer summary.

    Args:
        pdf: The PDF document to inspect.
        question: The epidemiology question to answer from the paper.
    """
    doc = PdfPlumberParser().parse(pdf)
    llm = default_client()
    found = Finder(llm).find(doc, question)
    report = DecisionStore(OUTPUTS / "decisions.json").apply(build_report(doc, question, found))
    print(to_text(report))

    # run log: every step's input and output, for traceability
    runs = OUTPUTS / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = {
        "time": stamp,
        "question": question,
        "document": doc.document,
        "model": llm.model_id,
        "finder_output": found.model_dump(mode="json"),
        "answers": [x.model_dump(mode="json") for x in report.answers],
        "rejected": [{"draft": d.model_dump(mode="json"), "reason": r} for d, r in report.rejected],
    }
    (runs / f"{stamp}.json").write_text(json.dumps(log, indent=2))


def main() -> None:
    """Run the command-line interface for parsing PDFs and answering questions."""
    load_dotenv()
    ap = argparse.ArgumentParser(prog="epiextract")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="parse a PDF into elements")
    p.add_argument("pdf", type=Path)
    a = sub.add_parser("ask", help="ask a question about a PDF")
    a.add_argument("pdf", type=Path)
    a.add_argument("question")
    args = ap.parse_args()

    try:
        if args.cmd == "parse":
            parse_cmd(args.pdf)
        else:
            ask_cmd(args.pdf, args.question)
    except (RuntimeError, FileNotFoundError) as err:
        raise SystemExit(f"Error: {err}")
    except ValidationError as err:
        raise SystemExit(f"Error: the model's response could not be validated, so no answer is shown.\n{err}")
    except Exception as err:  # e.g. AWS access or network errors
        raise SystemExit(f"Error ({type(err).__name__}): {err}")


if __name__ == "__main__":
    main()
