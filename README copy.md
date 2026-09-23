# Trustworthy Evidence Extraction for Epidemiology

A prototype that helps scientists query and extract epidemiological values from research papers. Every answer is traceable to its source, and the scientist stays in control.

## The problem I am addressing

Scientists need values such as attack rates, case fatality rates and vaccine efficacy from long papers. These numbers are buried in text, tables and figures, so the real pain point is **information overload**.

These values feed modelling, risk assessment and guideline development. If a number is wrong, the decisions built on it are wrong too. So I treated a fast answer as worthless unless it is **accurate, transparent and defensible**.

## Where this fits, and why I chose this step

I reviewed the sample files to understand the pipeline before choosing a focus:

- The **GREP-Agent draft** (Cochrane-GREP-ExP-Screening-Draft) describes an LLM tool that screens articles by title and abstract. It frames the larger goal as automating the *identification and extraction* of epidemiological parameters. GREP-Agent covers identification.
- The **L1 screening CSV** is the output of that step: 99 citations with title/abstract metadata and three human screening labels. Only 14 pass all three criteria.
- The team's note confirms the CSV holds title/abstract information only, and that the PDFs do not necessarily match it.

So screening is already handled upstream. The step after it, getting reliable values out of the full papers, is where I focused. I use the GREP-Agent draft as my requirements: it shows what epidemiologists want answered.

## My focus: AI assists, the scientist decides

I address two core problems.

**1. Trust.** Every value shows where it came from: document, page, table and quote. If no source supports an answer, the system says "not found" instead of guessing.
*Reasoning:* in 3.pdf I found five internal inconsistencies. For example, Table 1 reports an attack rate of 6.2%, but its own counts give 1,204 / 193,931 = 0.62%. A standard AI tool would copy 6.2% with a correct citation. A citation proves where a number came from, not that it is right.

**2. Control.** The scientist can check any source in one click, and accept, reject or exclude values or sources. Nothing is removed silently.
*Reasoning:* the GREP-Agent design itself keeps humans in the loop, sending uncertain cases to a reviewer. I apply the same principle: the AI reduces workload, but the final decision belongs to the scientist.

These two goals pull against each other. More evidence on screen builds trust but adds to the overload I am trying to reduce. So I show the answer first and the evidence on demand.

## Priorities

| Priority | What | Why |
|---|---|---|
| Core | Read sources correctly and show where each value came from | Traceability cannot be added later; it must be captured at extraction |
| Core | Let the scientist exclude doubtful values or sources, with a reason | Keeps the scientist in control, and exclusions stay traceable |
| Extra | Validate content: recompute rates, compare text and tables | Catches errors in the paper itself, like 3.pdf's attack rate |

## Approach

- **Step 0: profile sources.** I label each part of a PDF by reliability: digital tables and text are more reliable than scanned text, and figures are least reliable. I do this per element, not per file, because 3.pdf alone contains digital text, tables and figure images.
- **Agent 1 (Finder):** understands the query and extracts values, recording the source at the moment of extraction.
- **Agent 2 (Checker):** understands the question and uses code-based tools to verify values. It also checks scope: asked for the under-5 CFR, the all-ages 1.2% is flagged as not answering the question.
- **Agent 3 (Reporter):** presents answers with sources and flags. No source, no answer.

**The LLM reads and decides; code does anything that must be exact.** LLMs are unreliable at arithmetic, so recalculation and comparison are plain code.

## Out of scope

- Screening, handled upstream by GREP-Agent
- Production deployment and scale

## Development stages

| Stage | Goal | Status |
|---|---|---|
| 1. Core | Read the source correctly and answer with sources | ✅ This version (`v0.1`) |
| 2. Trust | Agent 2: recompute rates, compare mentions, check scope; gold set and evaluation | Planned |
| 3. Control and polish | Exclusion with reasons, simple UI, Textract + Terraform resources | Planned |

## What Stage 1 does

1. **Parse** a PDF into elements (paragraphs, tables, figures). Each element has an ID (`p3-table1`), page, position, section and reliability tier. Two-column layouts are read column by column, and tables keep their rows (`Total | 1204 | 14 | 1.2`).
2. **Find** (Agent 1): an LLM on Amazon Bedrock answers the question in the extraction schema, citing an element ID and an exact quote. Temperature 0; the output is validated with Pydantic, with one retry if invalid.
3. **Report** (Agent 3): code checks that the cited element exists and that the quote really appears in it. Answers that fail are not shown as answers. If nothing is supported, the result is "NOT FOUND".

Every `ask` run is logged to `outputs/runs/` (question, model, raw finder output, accepted and rejected answers).

### Design decisions

- **The system fills what it knows.** The LLM names only the element ID and quote; document, page and tier come from the parser, so they cannot be hallucinated.
- **Figures are not read yet.** Figure elements hold only their caption and are tier 4. Answers citing them are rejected rather than trusted.
- **Text cleaning must not change numbers.** Line-break hyphens are joined only between letters, so `(2828- 1478)` keeps its minus sign. There is a test for this.
- **Swappable services.** `DocumentParser` and `LLMClient` are interfaces. Stage 1 uses pdfplumber (local, for digital PDFs) and Bedrock. Textract, or Azure Document Intelligence and Azure OpenAI in production, plug in without changing the pipeline.
- **Replay without credentials.** `CachedLLM` saves every model response under `cache/llm/` and replays it, so a recorded demo runs without AWS access.

### Known limitations

- The local parser is tuned to common two-column journal layouts (e.g. tables drawn with three horizontal rules). Other layouts need Textract.
- Scanned pages are detected and marked, but not OCR'd yet.
- Stage 1 checks that a value is *cited correctly*, not that it is *correct*. Checking the content itself is Stage 2.

## Getting started

Sample PDFs are not committed. Put them in `data/` (e.g. `data/3.pdf`).

```bash
cp .env.example .env        # add BEDROCK_MODEL_ID and AWS credentials to run live

# with Docker
docker compose build
docker compose run --rm test                                   # run tests
docker compose run --rm app parse data/3.pdf                   # parse only (no AWS needed)
docker compose run --rm app ask data/3.pdf "What was the case fatality rate?"

# without Docker
pip install -r requirements.txt
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m epiextract.cli ask data/3.pdf "What was the case fatality rate?"
```

## Repository structure

```
src/epiextract/
  schema.py     # Element and shape-based Extraction models
  parser.py     # DocumentParser interface + PdfPlumberParser
  llm.py        # LLMClient interface + BedrockClient + CachedLLM (replay)
  finder.py     # Agent 1: extract values with element ID and quote
  reporter.py   # Agent 3: grounding checks, "no source, no answer", output
  cli.py        # parse / ask commands, run logs
tests/          # parser, grounding and schema tests (no AWS needed)
terraform/      # AWS provider (resources added with Textract in Stage 3)
data/ outputs/ cache/   # local only, git-ignored
```
