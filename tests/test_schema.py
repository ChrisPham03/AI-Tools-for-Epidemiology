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
