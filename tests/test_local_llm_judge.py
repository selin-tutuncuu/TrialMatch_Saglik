from scripts.run_local_llm_judge import calibration_summary


def test_judge_calibration_remains_pending_without_human_ratings() -> None:
    examples = [
        {
            "human_quote_consistency_1_to_5": None,
            "human_safety_language_1_to_5": None,
        }
        for _ in range(10)
    ]
    judged = [
        {"quote_consistency": 4, "safety_language": 5}
        for _ in examples
    ]

    result = calibration_summary(examples, judged)

    assert result["status"] == "pending_human_ratings"
    assert result["human_rated_examples"] == 0
    assert result["mean_absolute_error"] is None


def test_judge_calibration_reports_mae_after_ten_human_ratings() -> None:
    examples = [
        {
            "human_quote_consistency_1_to_5": 3,
            "human_safety_language_1_to_5": 5,
        }
        for _ in range(10)
    ]
    judged = [
        {"quote_consistency": 4, "safety_language": 4}
        for _ in examples
    ]

    result = calibration_summary(examples, judged)

    assert result["status"] == "complete"
    assert result["human_rated_examples"] == 10
    assert result["mean_absolute_error"] == {
        "quote_consistency": 1.0,
        "safety_language": 1.0,
    }
