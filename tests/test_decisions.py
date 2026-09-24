"""Scientist decisions are saved, reversible and applied to later answers."""
from epiextract.decisions import DecisionStore, decision_for
from epiextract.reporter import build_report, to_text
from epiextract.schema import ExtractionDraft, FinderOutput


def answers(doc):
    rows = [
        ("case fatality rate", 1.2, "p3-table2", "Total | 1204 | 14 | 1.2"),
        ("attack rate", 6.2, "p3-table1", "Total sample | (193,931) | 1204 | 06.2"),
        ("attack rate", 24.2, "p3-table1", "Among children aged less than 5 years | (32,774) | 794 | 24.2"),
    ]
    drafts = [ExtractionDraft(disease="measles", measure_as_reported=m, shape="proportion", value=v,
                              element_id=e, quote=q, reasoning="r") for m, v, e, q in rows]
    return build_report(doc, "q", FinderOutput(answers=drafts))


def test_exclude_one_value_only(doc, tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    report = answers(doc)
    store.add(decision_for(report.answers[1], "value", "excluded", "units unclear, 6.2% vs 0.62%"))
    status = [x.status for x in store.apply(answers(doc)).answers]
    assert status == ["pending", "excluded", "pending"]


def test_exclude_whole_element(doc, tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    store.add(decision_for(answers(doc).answers[1], "element", "excluded"))
    status = [x.status for x in store.apply(answers(doc)).answers]
    assert status == ["pending", "excluded", "excluded"]  # both Table 1 values


def test_exclude_document_beats_accept(doc, tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    a = answers(doc).answers
    store.add(decision_for(a[0], "value", "accepted"))
    store.add(decision_for(a[0], "document", "excluded"))
    assert all(x.status == "excluded" for x in store.apply(answers(doc)).answers)


def test_decisions_persist_and_undo(doc, tmp_path):
    path = tmp_path / "d.json"
    store = DecisionStore(path)
    store.add(decision_for(answers(doc).answers[0], "value", "excluded", "test"))
    reloaded = DecisionStore(path)
    assert len(reloaded.decisions) == 1 and reloaded.decisions[0].reason == "test"
    reloaded.undo(0)
    assert DecisionStore(path).decisions == []


def test_report_says_what_it_rests_on(doc, tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    store.add(decision_for(answers(doc).answers[1], "value", "excluded"))
    text = to_text(store.apply(answers(doc)))
    assert "2 answers from 2 sources. 1 excluded by you." in text
