# Trustworthy Evidence Extraction for Epidemiology

A prototype AI tool that helps epidemiologists get values (attack rates, case fatality rates, vaccine efficacy) out of research papers. Every answer shows exactly where it came from, and the scientist decides what to trust.

## Summary

### The problem

Epidemiologists gather evidence to support modelling, risk assessment and guideline development. Their pain point is data gathering: too many sources, and information overload. AI can help, but it can still hallucinate. So this tool helps with the work that slows scientists down, and the final decision stays with them.

Screening (deciding which papers belong in a review) is handled upstream by GREP-Agent. This project focuses on the next step: getting reliable values out of full papers.

### My focus

I started from one use case: a scientist asks for a metric, and the AI gives an answer. That raises three questions: how do we know it is accurate, how can we trust it, and how can we check it? The prototype addresses two core issues:

1. **Accuracy.** If the data is wrong, the decision is wrong. To check an answer, we need to track its source, so every answer carries its page, table or paragraph, and an exact quote.
2. **Controllability.** Once the source is visible, the scientist must be able to exclude an ambiguous one. Exclusions are saved, reapplied to later questions, and reversible.

### Approach: divide and conquer

The expected output is a highly correct answer with its source. Working back from that, the task splits into four parts, grouped into a parser and three agents:

| Part | Component | What it does | Status |
|---|---|---|---|
| Find and parse | Parser | Breaks a PDF into labelled pieces (paragraphs, tables, figures) with page, position and a reliability tier | Built |
| Extract | Agent 1: Finder | LLM extracts values in a fixed format, citing a piece and an exact quote | Built |
| Check | Agent 2: Checker | Code confirms the quote is really in the cited piece | Built (lives in `reporter.py`) |
| | | Code checks the numbers themselves (recompute rates, compare text and tables) | **Not built** (time) |
| Present and control | Agent 3: Reporter + app | Shows the answer with the page highlighted; scientist accepts or excludes | Built |

The rule across all components: **the LLM reads, code checks, the scientist decides.**

### Tools and why

| Tool | Why |
|---|---|
| pdfplumber | Gives every word with its position, which traceability needs; runs locally |
| Pydantic | Defines the answer format and rejects malformed model output |
| Amazon Bedrock (Nova Lite) | Existing AWS access; the Canada inference profile keeps data in Canada |
| Streamlit | A working interface in pure Python |
| pytest, Docker | Tests without AWS; one-command setup |

Azure OpenAI and Azure Document Intelligence are the intended production platform, to match the Government of Canada's Microsoft environment. The parser and LLM sit behind interfaces (`DocumentParser`, `LLMClient`), so switching means two new classes.

### Challenges and trade-offs

- **A correct source is not a correct number.** The sample paper reports an attack rate of 6.2%, but its own counts (1,204 / 193,931) give 0.62%. It has four more internal contradictions. The prototype cites these faithfully; catching them is the unbuilt number check.
- **Strict grounding costs recall.** Answers whose quote cannot be matched are not shown. This is safe, but a correct answer can be hidden; such answers are listed as unverified candidates instead.
- **Transparency vs overload.** More evidence builds trust but adds clutter, so the app shows the answer first and the evidence on demand.
- **Messy inputs.** Two-column layouts, wrapped table rows, figures and scanned pages. The local parser handles common journal layouts; scans and figures are not read yet.

### Validation

- **Grounding:** code checks every quote against its source. Page, tier and section come from the parser, never the model.
- **Abstaining:** the model may answer "not found", and does for values the paper does not report.
- **Reliability tiers:** 1 digital table, 2 digital text, 3 scanned page, 4 figure (not read, never trusted alone).
- **Live testing** on Bedrock found three failures, all safe: a cleaning step merged two numbers, a wrapped table row caused a correct answer to be rejected, and an empty model answer crashed the run. All are fixed and covered by tests (29 in total, none needing AWS).

**Next:** number checks (recompute, compare, check sums and scope), a hand-checked gold set with an evaluation script, OCR for scans, reading figures, search across many papers, and the move to Azure.

### How this was built

I did the analysis, chose the focus, designed the components and tested the prototype live. Claude, an AI assistant, wrote the code, tests and documentation, and fixed the failures testing found. **I have not yet reviewed every line of the code.** I verified its behaviour through the test suite and live runs, and a full review is my next step.

## Running it

Sample PDFs are not committed. Put them in `data/` (for example `data/3.pdf`).

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the tests (no AWS needed)

```bash
PYTHONPATH=src python -m pytest -q      # expect 29 passed
```

### 3. Connect to Amazon Bedrock

1. In the AWS console, open Amazon Bedrock and check a model runs in the playground (Nova Lite needs no sign-up form).
2. Find the model and its Canada inference profile:
   ```bash
   aws bedrock list-inference-profiles --region ca-central-1 \
     --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'nova-lite')].inferenceProfileId" --output text
   ```
3. Create `.env` (never committed):
   ```
   AWS_REGION=ca-central-1
   BEDROCK_MODEL_ID=ca.amazon.nova-lite-v1:0
   ```
   Credentials come from your AWS CLI setup (`aws configure`); add `AWS_PROFILE=<name>` to use a named profile.

Without Bedrock, the app replays saved answers from `cache/llm/` for questions that were asked before.

### 4. Start the app

```bash
PYTHONPATH=src streamlit run src/epiextract/app.py
```

Opens at http://localhost:8501. Pick a paper, ask a question or click an example, open "Show on the page", and accept or exclude answers.

### 5. Command line (optional)

```bash
PYTHONPATH=src python -m epiextract.cli parse data/3.pdf
PYTHONPATH=src python -m epiextract.cli ask data/3.pdf "What was the case fatality rate?"
```

Each `ask` writes a run log to `outputs/runs/`. Decisions are stored in `outputs/decisions.json`.

### With Docker

```bash
docker compose build
docker compose up ui                 # app at http://localhost:8501
docker compose run --rm test         # tests
```

## Repository structure

```
src/epiextract/
  schema.py     data shapes: Element (a piece of a PDF), ExtractionDraft (one answer)
  parser.py     PDF into elements with page, position and tier
  llm.py        Bedrock client (forced JSON format) and response cache
  finder.py     Agent 1: extraction prompt
  reporter.py   Agent 3 and the quote check: no source, no answer
  decisions.py  accept and exclude, saved and reapplied
  evidence.py   page image with the cited region highlighted
  app.py        Streamlit app
  cli.py        command line and run logs
tests/          29 tests, no AWS needed
terraform/      AWS provider skeleton for later resources
```