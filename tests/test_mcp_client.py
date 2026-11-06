import json
from types import SimpleNamespace

import pytest

from trialmatch.clinicaltrials import TrialApiError
from trialmatch.mcp_client import _raise_tool_error, _result_value


def test_mcp_structured_result_unwraps_fastmcp_result_envelope() -> None:
    payload = json.dumps([{"nct_id": "NCT01234567"}])
    assert _result_value(SimpleNamespace(structuredContent={"result": payload})) == payload


def test_mcp_text_content_is_used_when_no_structured_result_exists() -> None:
    content = [SimpleNamespace(text="NOT_FOUND")]
    assert _result_value(SimpleNamespace(structuredContent=None, content=content)) == "NOT_FOUND"


def test_mcp_tool_error_is_not_mistaken_for_a_json_trial() -> None:
    result = SimpleNamespace(
        isError=True,
        content=[SimpleNamespace(text="ClinicalTrials.gov returned HTTP 429.")],
    )
    with pytest.raises(TrialApiError, match="HTTP 429"):
        _raise_tool_error(result, "get_trial")
