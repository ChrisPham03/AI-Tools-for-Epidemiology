"""Streamlit app: ask a paper, check every answer against its source, and decide.

Run:  PYTHONPATH=src streamlit run src/epiextract/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow `streamlit run` without PYTHONPATH

import streamlit as st
from dotenv import load_dotenv

from epiextract.decisions import DecisionStore, decision_for
from epiextract.evidence import page_region
from epiextract.finder import Finder
from epiextract.llm import default_client
from epiextract.parser import PdfPlumberParser
from epiextract.reporter import _fmt_value, build_report

load_dotenv()
DATA, OUTPUTS = Path("data"), Path("outputs")
TIER_LABEL = {1: "digital table", 2: "digital text", 3: "scanned page", 4: "figure (not read)"}
EXAMPLES = [
    "What was the case fatality rate?",
    "What was the overall attack rate?",
    "What was the attack rate in children under 5?",
    "What is the incubation period of measles?",
]

st.set_page_config(page_title="Ask a paper", page_icon="🔎", layout="wide")
st.markdown(
    """<style>
    .value {font-size: 2rem; font-weight: 600; line-height: 1.1; margin: 0;}
    .measure {font-size: 1.05rem; margin: 0 0 .4rem 0;}
    .meta {color: #5B6475; font-size: .9rem; margin: 0;}
    .quote {border-left: 3px solid #A86B12; padding: .2rem 0 .2rem .7rem; margin: .5rem 0;
            color: #1C2B3A; font-size: .92rem; white-space: pre-wrap;}
    .status-accepted {color: #2F6F4F; font-weight: 600;}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Reading the document…")
def parse(path: str, mtime: float):
    return PdfPlumberParser().parse(path)


store = DecisionStore(OUTPUTS / "decisions.json")

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Document")
    pdfs = sorted(DATA.glob("*.pdf"))
    if not pdfs:
        st.info("Put a PDF in the data/ folder to begin.")
        st.stop()
    pdf = st.selectbox("Paper", pdfs, format_func=lambda p: p.name)
    doc = parse(str(pdf), pdf.stat().st_mtime)
    counts = {t: sum(e.type.value == t for e in doc.elements) for t in ("text", "table", "figure")}
    st.caption(f"{doc.pages} pages. {counts['text']} paragraphs, {counts['table']} tables, "
               f"{counts['figure']} figures (captions only).")

    llm = default_client()
    live = getattr(llm, "live", None) is not None
    st.caption(f"Model: {llm.model_id}" + ("" if live else " (replay only: saved answers)"))

    st.header("Your decisions")
    if not store.decisions:
        st.caption("None yet. Accept or exclude answers to record them here.")
    for i, d in enumerate(store.decisions):
        st.caption(d.describe())
        if st.button("Undo", key=f"undo-{i}"):
            store.undo(i)
            st.rerun()

# ------------------------------------------------------------------- ask
st.title("Ask a paper")
st.write("Every answer shows where it came from. Nothing is shown unless its quote is found in the paper.")

cols = st.columns(len(EXAMPLES))
for c, q in zip(cols, EXAMPLES):
    if c.button(q, use_container_width=True):
        st.session_state.question = q
        st.session_state.run = True

question = st.text_input("Question", key="question", placeholder="e.g. What was the case fatality rate?")
if st.button("Ask", type="primary") or st.session_state.pop("run", False):
    if question.strip():
        try:
            with st.spinner("Reading the paper for your answer…"):
                found = Finder(llm).find(doc, question)
            st.session_state.result = (pdf.name, question, found)
        except Exception as err:  # clear message, never a traceback
            st.session_state.pop("result", None)
            st.error(f"Could not get an answer: {err}")

result = st.session_state.get("result")
if not result or result[0] != pdf.name:
    st.stop()

_, asked, found = result
report = store.apply(build_report(doc, asked, found))
shown = [x for x in report.answers if x.status != "excluded"]
excluded = [x for x in report.answers if x.status == "excluded"]

# ---------------------------------------------------------------- summary
st.subheader(asked)
if shown:
    sources = {x.source.element_id for x in shown}
    line = f"{len(shown)} answer{'s' if len(shown) != 1 else ''} from {len(sources)} source{'s' if len(sources) != 1 else ''}."
    if excluded:
        line += f" {len(excluded)} excluded by you."
    st.write(line)
elif report.rejected:
    st.warning("No verified answer. A candidate was found but its quote could not be matched "
               "to the paper. Check it below.")
elif excluded:
    st.info("The only answer was excluded by you. Undo it from the sidebar." if len(excluded) == 1
            else f"All {len(excluded)} answers were excluded by you. Undo from the sidebar.")
else:
    st.info("Not found in this paper." + (f" {report.not_found_reason}" if report.not_found_reason else ""))

# ---------------------------------------------------------------- answers
for i, x in enumerate(shown):
    d, s = x.draft, x.source
    element = doc.get(s.element_id)
    with st.container(border=True):
        left, right = st.columns([2, 3])
        with left:
            status = '<span class="status-accepted">Accepted</span>' if x.status == "accepted" else ""
            st.markdown(f'<p class="value">{_fmt_value(d)}</p>'
                        f'<p class="measure">{d.measure_as_reported} {status}</p>', unsafe_allow_html=True)
            context = [f"Population: {d.population}" if d.population else None,
                       f"Location: {d.location}" if d.location else None,
                       f"Period: {d.study_period}" if d.study_period else None]
            st.markdown("".join(f'<p class="meta">{c}</p>' for c in context if c), unsafe_allow_html=True)
            st.markdown(f'<p class="meta">Page {s.page}, {s.element_id}, {s.section or "no section"}. '
                        f'Read from {TIER_LABEL[s.tier]}.</p>', unsafe_allow_html=True)
            st.markdown(f'<div class="quote">{s.quote}</div>', unsafe_allow_html=True)

            a, b = st.columns(2)
            if a.button("Accept", key=f"acc-{i}", disabled=x.status == "accepted"):
                store.add(decision_for(x, "value", "accepted"))
                st.rerun()
            with b.popover("Exclude"):
                scope = st.radio("Exclude", ["value", "element", "document"], key=f"scope-{i}",
                                 format_func={"value": "This value only",
                                              "element": f"Everything from {s.element_id}",
                                              "document": f"Everything from {s.document}"}.get)
                reason = st.text_input("Reason", key=f"reason-{i}", placeholder="e.g. units unclear")
                if st.button("Exclude", key=f"exc-{i}", type="primary"):
                    store.add(decision_for(x, scope, "excluded", reason))
                    st.rerun()
        with right:
            with st.expander("Show on the page", expanded=i == 0):
                zoom = st.toggle("Zoom in on the source", key=f"zoom-{i}")
                st.image(page_region(pdf, s.page, element.bbox, full_page=not zoom),
                         caption=f"{s.document}, page {s.page}: cited region highlighted")
            st.caption(f"Why: {d.reasoning}")

# ------------------------------------------------------ everything else
if excluded:
    with st.expander(f"Excluded by you ({len(excluded)})"):
        for x in excluded:
            st.write(f"{x.draft.measure_as_reported}: {_fmt_value(x.draft)} ({x.source.element_id})")
        st.caption("Undo from the sidebar.")

if report.rejected:
    with st.expander(f"Unverified candidates ({len(report.rejected)})", expanded=not shown):
        for d, problem in report.rejected:
            st.write(f"{d.measure_as_reported} = {d.value} (cited {d.element_id}): {problem}")
            st.markdown(f'<div class="quote">{d.quote}</div>', unsafe_allow_html=True)

if report.malformed:
    with st.expander(f"Model answers dropped ({len(report.malformed)})"):
        st.caption("These broke the schema rules and are kept in the run log.")
        for m in report.malformed:
            st.write(m)