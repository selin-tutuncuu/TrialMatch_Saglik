from trialmatch.presentation import trial_display_title


def test_trial_display_title_summarizes_breast_cancer_study() -> None:
    assert trial_display_title(
        "A Study in Participants With Advanced Breast Cancer"
    ) == "İleri evre meme kanseri araştırması"


def test_trial_display_title_preserves_her2_negative_subtype() -> None:
    assert trial_display_title(
        "Study in HER2-Negative Advanced Breast Cancer"
    ) == "İleri evre HER2-negatif meme kanseri araştırması"


def test_trial_display_title_uses_general_label_for_other_studies() -> None:
    assert trial_display_title("A Study in Breast Cancer") == "Meme kanseri araştırması"
    assert trial_display_title("A Study of another condition") == "Klinik araştırma"
