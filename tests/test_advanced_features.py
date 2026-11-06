from __future__ import annotations

import json

from scripts.evaluate_criterion_models import leave_one_case_out, load_examples
from scripts.run_trec_baselines import load_topic_files, run_evaluation
from trialmatch.agents import ReportAgent
from trialmatch.criterion_classifier import NaiveBayesCriterionClassifier
from trialmatch.models import TrialEvaluation, TrialSummary


def test_synthetic_small_classifier_trains_and_predicts_a_supported_label() -> None:
    examples = load_examples()
    classifier = NaiveBayesCriterionClassifier()
    classifier.fit(examples)
    prediction = classifier.predict(
        "54 yaş kadın, meme kanseri, HER2 pozitif.",
        "HER2-positive disease.",
    )
    assert prediction in {"MET", "NOT_MET", "UNKNOWN"}
    assert len(leave_one_case_out(examples)["per_example"]) == len(examples)


def test_trec_baselines_return_b1_and_terminology_ablation_metrics() -> None:
    topic_data = {
        "dataset": "synthetic-fixture",
        "query_ids": ["1"],
        "topics": {"1": "breast cancer HER2"},
        "qrels": [
            {"query_id": "1", "doc_id": "NCT00000001", "relevance": 2},
            {"query_id": "1", "doc_id": "NCT00000002", "relevance": 0},
        ],
        "documents": {
            "NCT00000001": "breast cancer HER2 study",
            "NCT00000002": "unrelated eye condition study",
        },
    }
    results = run_evaluation(
        topic_data,
        {"her2 pozitif": ["her2 positive", "her2+"]},
    )
    assert results["topics"] == 1
    assert results["B1"]["macro_P@10"] == 0.1
    assert results["terminology_expanded"]["macro_P@10"] == 0.1


def test_report_ranking_uses_nearest_center_after_safety_group() -> None:
    def evaluation(nct_id: str, distance: float, status: str) -> TrialEvaluation:
        return TrialEvaluation(
            trial=TrialSummary(
                nct_id=nct_id,
                title="Synthetic study",
                status="RECRUITING",
                distance_km=distance,
                source_url=f"https://clinicaltrials.gov/study/{nct_id}",
                fetched_at="2026-01-01T00:00:00Z",
            ),
            criteria=[],
            screening_status=status,
            score=0.5,
            unknown_count=1,
        )

    farther = evaluation("NCT00000001", 20, "needs_more_information")
    closer = evaluation("NCT00000002", 5, "needs_more_information")
    excluded = evaluation("NCT00000003", 1, "does_not_appear_to_meet")
    ranked = ReportAgent().run([farther, excluded, closer], limit=3)
    assert [item.trial.nct_id for item in ranked] == [
        "NCT00000002",
        "NCT00000001",
        "NCT00000003",
    ]


def test_trec_snapshot_files_merge_to_25_unique_year_prefixed_topics(tmp_path) -> None:
    paths = []
    for year, count in (("2021", 15), ("2022", 10)):
        query_ids = [str(value) for value in range(1, count + 1)]
        payload = {
            "query_ids": query_ids,
            "topics": {query_id: f"topic {year} {query_id}" for query_id in query_ids},
            "qrels": [
                {
                    "query_id": query_id,
                    "doc_id": f"NCT{int(query_id):08d}",
                    "relevance": 1,
                }
                for query_id in query_ids
            ],
            "documents": {
                f"NCT{int(query_id):08d}": f"study {year} {query_id}"
                for query_id in query_ids
            },
        }
        path = tmp_path / f"trec_{year}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)

    merged = load_topic_files(paths)
    assert len(merged["query_ids"]) == 25
    assert "2021:1" in merged["topics"]
    assert "2022:1" in merged["topics"]
