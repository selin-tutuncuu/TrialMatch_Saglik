import json

import pytest

from scripts.run_trec_b0 import parse_nct_ids


def test_b0_id_parser_normalizes_and_deduplicates_ids() -> None:
    assert parse_nct_ids(
        '{"nct_ids":["nct12345678","NCT12345678","not-an-id","NCT00000001"]}'
    ) == ["NCT12345678", "NCT00000001"]


def test_b0_id_parser_rejects_non_json_or_wrong_shape() -> None:
    with pytest.raises(ValueError):
        parse_nct_ids("not json")
    with pytest.raises(ValueError, match="nct_ids list"):
        parse_nct_ids('{"ids":[]}')


def test_b0_id_parser_caps_output_at_ten() -> None:
    values = [f"NCT{number:08d}" for number in range(12)]
    assert len(parse_nct_ids(json.dumps({"nct_ids": values}))) == 10
