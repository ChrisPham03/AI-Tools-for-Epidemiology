import pytest
from pydantic import ValidationError

from epiextract.llm import inline_refs
from epiextract.schema import ExtractionDraft, FinderOutput


def test_shape_requires_its_main_value():
    with pytest.raises(ValidationError):
        ExtractionDraft(disease="measles", measure_as_reported="incubation period", shape="central_spread",
                        element_id="x", quote="y", reasoning="z")


def test_quote_is_required():
    with pytest.raises(ValidationError):
        ExtractionDraft(disease="measles", measure_as_reported="CFR", shape="proportion", value=1.2,
                        element_id="x", quote="", reasoning="z")


def test_tool_schema_has_no_refs():
    assert "$ref" not in str(inline_refs(FinderOutput.model_json_schema()))


def test_placeholder_answer_is_set_aside_not_fatal():
    # Real case from live testing: for a value the paper does not report, the model
    # returned a 'count' with no value. The run must continue and keep the evidence.
    valid = dict(disease="measles", measure_as_reported="CFR", shape="proportion", value=1.2,
                 element_id="p3-table2", quote="Total | 1204 | 14 | 1.2", reasoning="r")
    placeholder = dict(disease="measles", measure_as_reported="incubation period", shape="count",
                       element_id="none", quote="n/a", reasoning="not reported")
    out = FinderOutput.model_validate({"answers": [valid, placeholder]})
    assert len(out.answers) == 1
    assert len(out.invalid_answers) == 1
    assert "missing its main value" in out.invalid_answers[0].error


def test_model_is_not_asked_for_system_fields():
    from epiextract.llm import tool_schema
    assert "invalid_answers" not in tool_schema(FinderOutput)["properties"]


def test_cached_output_round_trips():
    out = FinderOutput.model_validate({"answers": [], "not_found_reason": "not reported"})
    assert FinderOutput.model_validate_json(out.model_dump_json()) == out
