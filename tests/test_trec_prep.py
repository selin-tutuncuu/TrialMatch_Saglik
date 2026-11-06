import json
from pathlib import Path

import pytest

from scripts.prepare_trec_eval import _document_text, parse_qrels_lines


def test_selected_trec_topics_include_all_breast_cancer_topics() -> None:
    selection_path = Path(__file__).resolve().parents[1] / "data/trec_qids.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selected = {
        dataset: {
            topic["query_id"]
            for topic in selection["topics"]
            if topic["dataset"] == dataset
        }
        for dataset in {
            topic["dataset"] for topic in selection["topics"]
        }
    }

    assert sum(map(len, selected.values())) == 25
    assert selected["clinicaltrials/2021/trec-ct-2021"] == {
        *(str(topic_id) for topic_id in range(1, 10)),
        "25",
        "39",
        "49",
        "50",
        "57",
        "61",
    }
    assert selected["clinicaltrials/2021/trec-ct-2022"] == {
        str(topic_id) for topic_id in range(1, 11)
    }


def test_trec_2022_qrels_parser_filters_to_selected_topics() -> None:
    rows = parse_qrels_lines(
        [
            "1 0 NCT00000001 2",
            "2 0 NCT00000002 1",
        ],
        {"1"},
    )
    assert rows == [{"query_id": "1", "doc_id": "NCT00000001", "relevance": 2}]


def test_trec_qrels_parser_rejects_malformed_selected_rows() -> None:
    with pytest.raises(ValueError, match="Malformed TREC qrels row"):
        parse_qrels_lines(["1 NCT00000001 2"], {"1"})


def test_trec_xml_extraction_includes_retrieval_fields() -> None:
    xml = b"""<clinical_study>
      <id_info><nct_id>NCT00000001</nct_id></id_info>
      <brief_title>Sample trial</brief_title>
      <condition>Breast cancer</condition>
      <brief_summary>Study summary</brief_summary>
      <eligibility><criteria>Adults with disease</criteria></eligibility>
    </clinical_study>"""
    nct_id, text = _document_text(xml)
    assert nct_id == "NCT00000001"
    assert "Sample trial" in text
    assert "Breast cancer" in text
    assert "Adults with disease" in text
