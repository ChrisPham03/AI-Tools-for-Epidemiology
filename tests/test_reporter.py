"""'No source, no answer': grounding checks run in plain code, without an LLM."""
from epiextract.finder import Finder
from epiextract.llm import LLMClient
from epiextract.reporter import build_report
from epiextract.schema import ExtractionDraft, FinderOutput


def draft(**kw):
    base = dict(disease="measles", measure_as_reported="case fatality rate", shape="proportion",
                value=1.2, element_id="p3-table2", quote="Total | 1204 | 14 | 1.2 | 214 (17.7)",
                reasoning="Table 2, row Total, column CFR")
    base.update(kw)
    return ExtractionDraft(**base)


class FakeLLM(LLMClient):
    model_id = "fake"

    def __init__(self, output):
        self.output = output

    def extract(self, system, prompt, schema):
        return self.output


def test_grounded_answer_is_kept_with_source(doc):
    report = build_report(doc, "q", FinderOutput(answers=[draft()]))
    assert len(report.answers) == 1
    src = report.answers[0].source
    assert (src.page, src.element_id, src.tier) == (3, "p3-table2", 1)


def test_quote_matching_ignores_cell_separators_and_spacing(doc):
    report = build_report(doc, "q", FinderOutput(answers=[draft(quote="Total  1204 14 1.2")]))
    assert len(report.answers) == 1


def test_invented_quote_is_rejected(doc):
    report = build_report(doc, "q", FinderOutput(answers=[draft(quote="Total | 1204 | 14 | 2.5")]))
    assert not report.answers and "quote not found" in report.rejected[0][1]


def test_unknown_element_is_rejected(doc):
    report = build_report(doc, "q", FinderOutput(answers=[draft(element_id="p9-table7")]))
    assert not report.answers and "does not exist" in report.rejected[0][1]


def test_values_from_unread_figures_are_rejected(doc):
    d = draft(element_id="p3-figure2", quote="Figure 2: Age wise case fatality rate in the study population")
    report = build_report(doc, "q", FinderOutput(answers=[d]))
    assert not report.answers and "not read" in report.rejected[0][1]


def test_not_found_is_reported(doc):
    out = FinderOutput(answers=[], not_found_reason="The paper does not report an incubation period.")
    found = Finder(FakeLLM(out)).find(doc, "What is the incubation period?")
    report = build_report(doc, "What is the incubation period?", found)
    assert not report.answers and report.not_found_reason


def test_unverified_candidate_is_not_called_not_found(doc):
    from epiextract.reporter import to_text
    report = build_report(doc, "q", FinderOutput(answers=[draft(quote="made-up quote")]))
    text = to_text(report)
    assert "NOT FOUND" not in text
    assert "No verified answer" in text and "made-up quote" in text


def test_under5_row_quote_now_matches(doc):
    d = draft(measure_as_reported="attack rate", value=24.2, element_id="p3-table1",
              quote="Among children aged less than 5 years | (32,774) | 794 | 24.2")
    assert len(build_report(doc, "q", FinderOutput(answers=[d])).answers) == 1