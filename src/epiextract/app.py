"""Streamlit app: ask a paper, check every answer against its source, and decide.

Run:  PYTHONPATH=src streamlit run src/epiextract/app.py
"""
from __future__ import annotations

import re
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
TIER_LABEL = {1: "a digital table", 2: "digital text", 3: "a scanned page", 4: "a figure (not read)"}
EXAMPLES = [
    "What was the case fatality rate?",
    "What was the overall attack rate?",
    "What was the attack rate in children under 5?",
    "What is the incubation period of measles?",
]

st.set_page_config(page_title="Ask a paper", page_icon="🔎", layout="wide")
st.markdown(
    """<style>
    @import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&family=Source+Serif+4:wght@600&display=swap');
    html, body, [class*="css"], .stMarkdown, .stTextInput, .stButton, p, li {font-family: 'Public Sans', Arial, sans-serif;}
    h1, h2, h3 {font-family: 'Source Serif 4', Georgia, serif !important; font-weight: 600 !important; color: #1C2B3A;}
    .block-container {padding-top: 2.2rem; max-width: 1280px;}
    .lede {color: #5B6475; font-size: 1.02rem; margin: -0.4rem 0 1.2rem 0;}
    [data-testid="stMarkdownContainer"] p.value {font-family: 'Source Serif 4', Georgia, serif !important;
            font-size: 2.8rem !important; font-weight: 600; line-height: 1.05; color: #1C2B3A; margin: 0;}
    [data-testid="stMarkdownContainer"] p.measure {font-size: 1.05rem !important; color: #1C2B3A;
            margin: .3rem 0 1rem 0;}
    .badge {display: inline-block; font-size: .8rem; font-weight: 600; padding: .15rem .55rem;
            border-radius: 999px; margin-left: .4rem; vertical-align: middle;}
    .b-verified {background: #E4F0E8; color: #2F6F4F;}
    .b-accepted {background: #E3ECF5; color: #2F5D8A;}
    .b-warn {background: #F6ECDA; color: #8A5A10;}
    .facts {display: grid; grid-template-columns: 7.5rem 1fr; row-gap: .3rem; font-size: .95rem; margin-bottom: 1rem;}
    .facts .k {color: #5B6475;}
    .facts .v {color: #1C2B3A;}
    .facts .none {color: #9AA1AD;}
    .source {border-top: 1px solid #DDE2E8; padding-top: .8rem; margin-top: .2rem;}
    .source .where {font-weight: 600; color: #1C2B3A;}
    .source .how {color: #5B6475; font-size: .9rem;}
    .quote {border-left: 3px solid #A86B12; background: #FBF8F2; padding: .55rem .8rem; margin: .7rem 0;
            color: #1C2B3A; font-size: .9rem; white-space: pre-wrap; border-radius: 0 6px 6px 0;}
    .why {color: #5B6475; font-size: .85rem; margin-bottom: .6rem;}
    .summary {font-size: .98rem; color: #1C2B3A; margin: .2rem 0 1rem 0;}
    .empty {border: 1px dashed #C9D0D8; border-radius: 10px; padding: 1.4rem 1.6rem; color: #5B6475;}
    </style>""",
    unsafe_allow_html=True,
)


def element_label(element_id: str) -> str:
    """'p3-table1' -> 'Table 1, page 3'; 'p3-text4' -> 'Paragraph 4, page 3'."""
    m = re.match(r"p(\d+)-(table|text|figure|image|page)(\d*)", element_id)
    if not m:
        return element_id
    page, kind, num = m.groups()
    name = {"table": "Table", "text": "Paragraph", "figure": "Figure", "image": "Image", "page": "Page"}[kind]
    return f"{name} {num}, page {page}".replace(" ,", ",") if kind != "page" else f"Page {page}"


def main_value(d) -> str:
    """The headline number only, e.g. '6.2%'; counts and spread are shown separately."""
    if d.shape.value == "central_spread":
        num = d.median if d.median is not None else d.mean
        label = "median " if d.median is not None else "mean "
    else:
        num, label = d.value, ""
    unit = "%" if d.unit in ("%", "percent") else (f" {d.unit}" if d.unit else "")
    return f"{label}{num:g}{unit}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


@st.cache_resource(show_spinner="Reading the paper…")
def parse(path: str, mtime: float):
    return PdfPlumberParser().parse(path)


store = DecisionStore(OUTPUTS / "decisions.json")

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Paper")
    pdfs = sorted(DATA.glob("*.pdf"))
    if not pdfs:
        st.info("Put a PDF in the data/ folder to begin.")
        st.stop()
    pdf = st.selectbox("Paper", pdfs, format_func=lambda p: p.name, label_visibility="collapsed")
    doc = parse(str(pdf), pdf.stat().st_mtime)
    counts = {t: sum(e.type.value == t for e in doc.elements) for t in ("text", "table", "figure")}
    st.caption(f"{plural(doc.pages, 'page')}, {plural(counts['table'], 'table')}, "
               f"{plural(counts['text'], 'paragraph')}. Figures are not read yet.")

    llm = default_client()
    live = getattr(llm, "live", None) is not None
    st.caption(f"Model: {llm.model_id}" + ("" if live else ". Replay only: saved answers."))

    st.divider()
    st.subheader("Your decisions")
    if not store.decisions:
        st.caption("None yet. Accepted and excluded answers are listed here, and can be undone.")
    for i, d in enumerate(store.decisions):
        with st.container(border=True):
            st.caption(d.describe())
            if st.button("Undo", key=f"undo-{i}"):
                store.undo(i)
                st.rerun()

# ------------------------------------------------------------------- ask
st.title("Ask a paper")
st.markdown('<p class="lede">Every answer comes with its source. Nothing is shown unless its quote '
            'is found in the paper, and you decide what to keep.</p>', unsafe_allow_html=True)


def use_example():
    choice = st.session_state.get("example")
    if choice:
        st.session_state.question = choice
        st.session_state.run = True


with st.form("ask", border=False):
    left, right = st.columns([6, 1], vertical_alignment="bottom")
    question = left.text_input("Question", key="question",
                               placeholder="e.g. What was the case fatality rate?")
    asked_now = right.form_submit_button("Ask", type="primary", width="stretch")
st.pills("Examples", EXAMPLES, key="example", on_change=use_example, label_visibility="collapsed")

if asked_now or st.session_state.pop("run", False):
    q = st.session_state.get("question", "").strip()
    if q:
        try:
            with st.spinner("Reading the paper for your answer…"):
                found = Finder(llm).find(doc, q)
            st.session_state.result = (pdf.name, q, found)
        except Exception as err:  # a clear message, never a traceback
            st.session_state.pop("result", None)
            st.error(f"Could not get an answer. {err}")

result = st.session_state.get("result")
if not result or result[0] != pdf.name:
    st.markdown(f'<div class="empty">Ask a question about <b>{pdf.name}</b>, or pick an example above.</div>',
                unsafe_allow_html=True)
    st.stop()

_, asked, found = result
report = store.apply(build_report(doc, asked, found))
shown = [x for x in report.answers if x.status != "excluded"]
excluded = [x for x in report.answers if x.status == "excluded"]

# ---------------------------------------------------------------- summary
st.subheader(asked)
if shown:
    parts = [plural(len(shown), "verified answer")]
    if excluded:
        parts.append(f"{len(excluded)} excluded by you")
    if report.rejected:
        parts.append(f"{len(report.rejected)} unverified")
    st.markdown(f'<p class="summary">{", ".join(parts)}.</p>', unsafe_allow_html=True)
elif report.rejected:
    st.warning("No verified answer. A candidate was found, but its quote could not be matched to the paper. "
               "Check it below.")
elif excluded:
    st.info("The only answer was excluded by you. Undo it in the sidebar." if len(excluded) == 1
            else f"All {len(excluded)} answers were excluded by you. Undo in the sidebar.")
else:
    st.info("Not found in this paper." + (f" {report.not_found_reason}" if report.not_found_reason else ""))

# ---------------------------------------------------------------- answers
for i, x in enumerate(shown):
    d, s = x.draft, x.source
    element = doc.get(s.element_id)
    with st.container(border=True):
        left, right = st.columns([5, 6], gap="large")
        with left:
            status = ('<span class="badge b-accepted">Accepted</span>' if x.status == "accepted"
                      else '<span class="badge b-verified">Quote found in source</span>')
            st.markdown(f'<p class="value">{main_value(d)}</p>'
                        f'<p class="measure">{d.measure_as_reported.capitalize()}{status}</p>',
                        unsafe_allow_html=True)

            def fact(label, value):
                v = f'<span class="v">{value}</span>' if value else '<span class="none">Not stated</span>'
                return f'<span class="k">{label}</span>{v}'
            counts = (f"{d.numerator:,.0f} / {d.denominator:,.0f}"
                      if d.numerator is not None and d.denominator is not None else None)
            rows = fact("Population", d.population) + fact("Location", d.location) + fact("Period", d.study_period)
            if counts:
                rows += fact("Counts", counts)
            st.markdown('<div class="facts">' + rows + "</div>", unsafe_allow_html=True)

            st.markdown(f'<div class="source"><span class="where">{element_label(s.element_id)}</span><br>'
                        f'<span class="how">{s.section or "No section"}. Read from {TIER_LABEL[s.tier]}.</span></div>'
                        f'<div class="quote">{s.quote}</div>'
                        f'<div class="why">Why: {d.reasoning}</div>', unsafe_allow_html=True)

            a, b, _ = st.columns([1, 1, 1])
            if a.button("Accept", key=f"acc-{i}", disabled=x.status == "accepted", width="stretch"):
                store.add(decision_for(x, "value", "accepted"))
                st.rerun()
            with b.popover("Exclude", width="stretch"):
                scope = st.radio("What to exclude", ["value", "element", "document"], key=f"scope-{i}",
                                 format_func={"value": "This value only",
                                              "element": f"Everything from {element_label(s.element_id)}",
                                              "document": f"Everything from {s.document}"}.get)
                reason = st.text_input("Reason", key=f"reason-{i}", placeholder="e.g. units unclear")
                if st.button("Exclude", key=f"exc-{i}", type="primary"):
                    store.add(decision_for(x, scope, "excluded", reason))
                    st.rerun()
        with right:
            zoom = st.toggle("Zoom in on the source", key=f"zoom-{i}")
            st.image(page_region(pdf, s.page, element.bbox, full_page=not zoom),
                     caption=f"{s.document}, page {s.page}. Cited region highlighted.",
                     width="stretch" if zoom else 440)

# ------------------------------------------------------ everything else
if report.rejected:
    with st.expander(f"Unverified candidates ({len(report.rejected)})", expanded=not shown):
        st.caption("The model gave these, but their quotes were not found in the cited part of the paper.")
        for d, problem in report.rejected:
            st.markdown(f'**{d.measure_as_reported}: {d.value}** <span class="badge b-warn">{problem}</span>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="quote">{d.quote}</div>', unsafe_allow_html=True)

if excluded:
    with st.expander(f"Excluded by you ({len(excluded)})"):
        for x in excluded:
            st.write(f"{x.draft.measure_as_reported}: {_fmt_value(x.draft)}, {element_label(x.source.element_id)}")
        st.caption("Undo in the sidebar.")

if report.malformed:
    with st.expander(f"Model answers set aside ({len(report.malformed)})"):
        st.caption("These broke the answer format and are kept in the run log.")
        for m in report.malformed:
            st.write(m)