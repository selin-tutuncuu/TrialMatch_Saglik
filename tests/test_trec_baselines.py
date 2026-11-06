from scripts.run_trec_baselines import _criterion_rerank


def test_final_trec_reranker_prefers_supported_trial_over_failed_age_criterion() -> None:
    documents = {
        "NCT00000001": (
            "Title: HER2-positive breast cancer study\n"
            "Condition: breast cancer\n"
            "Eligibility: Inclusion Criteria:\n- Age at least 70 years.\n"
            "- HER2-positive disease."
        ),
        "NCT00000002": (
            "Title: HER2-positive breast cancer study\n"
            "Condition: breast cancer\n"
            "Eligibility: Inclusion Criteria:\n- Age at least 18 years.\n"
            "- HER2-positive disease.\n"
            "Exclusion Criteria:\n- Active brain metastases."
        ),
    }

    ranked = _criterion_rerank(
        "54-year-old woman with HER2-positive breast cancer.",
        ["NCT00000001", "NCT00000002"],
        documents,
    )

    assert ranked == ["NCT00000002", "NCT00000001"]
