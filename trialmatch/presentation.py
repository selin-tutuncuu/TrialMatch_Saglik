from __future__ import annotations

from trialmatch.models import CriterionEvaluation, PatientProfile, TrialEvaluation


_SEX_LABELS = {
    "female": "Kadın",
    "male": "Erkek",
    "unknown": "Belirtilmedi",
}
_DECISION_LABELS = {
    "MET": "Kanıt maddeyi destekliyor",
    "NOT_MET": "Kanıt maddeyle çelişiyor",
    "UNKNOWN": "Bilgi yetersiz",
}
_SCREENING_LABELS = {
    "possible_match_for_clinician_review": "Uzman incelemesine öncelik verilebilir",
    "needs_more_information": "Ek bilgi gerekiyor",
    "does_not_appear_to_meet": "Karşılanmayan maddeler olabilir",
}
_KIND_LABELS = {
    "inclusion": "Dahil edilme maddesi",
    "exclusion": "Dışlama maddesi",
    "unspecified": "Türü belirlenemedi",
}


def profile_cards(profile: PatientProfile) -> list[tuple[str, str]]:
    biomarkers = ", ".join(
        " ".join(part for part in (item.name, item.value) if part)
        for item in profile.biomarkers
    ) or "Belirtilmedi"
    treatments = ", ".join(profile.prior_treatments) or "Belirtilmedi"
    comorbidities = ", ".join(profile.comorbidities) or "Belirtilmedi"
    return [
        ("Tanı", profile.diagnosis or "Belirtilmedi"),
        ("Evre", profile.stage or "Belirtilmedi"),
        ("Yaş", f"{profile.age} yaş" if profile.age is not None else "Belirtilmedi"),
        ("Cinsiyet", _SEX_LABELS[profile.sex]),
        ("Biyobelirteçler", biomarkers),
        ("Önceki tedaviler", treatments),
        ("Eşlik eden durumlar", comorbidities),
        ("Şehir", profile.location or "Belirtilmedi"),
    ]


def decision_label(decision: CriterionEvaluation) -> str:
    if decision.decision == "UNKNOWN":
        return "Bilgi yetersiz"
    if decision.kind == "exclusion":
        return (
            "Dışlama maddesiyle uyumlu bulgu var"
            if decision.decision == "MET"
            else "Dışlama maddesiyle uyumlu bulgu belirtilmemiş"
        )
    if decision.kind == "unspecified":
        return "Uzman incelemesi gerekli"
    return _DECISION_LABELS[decision.decision]


def criterion_explanation(decision: CriterionEvaluation) -> str:
    if decision.decision == "UNKNOWN":
        return (
            "Vaka özetinde bu maddeyi değerlendirmeye yetecek açık bilgi yok. "
            "Eksik bilgi uzman tarafından doğrulanmalı."
        )
    evidence = decision.patient_evidence or ""
    if "yaş" in evidence.casefold():
        return "Özette bildirilen yaş, kaynaktaki yaş maddesiyle karşılaştırıldı."
    if any(term in evidence.casefold() for term in ("kadın", "erkek", "female", "male")):
        return "Özette bildirilen cinsiyet bilgisi kaynak maddesiyle karşılaştırıldı."
    if any(term in evidence.casefold() for term in ("her2", "er ", "pr ", "brca", "ki-67", "pd-l1")):
        return "Özette bildirilen biyobelirteç bilgisi kaynak maddesiyle karşılaştırıldı."
    if evidence and any(
        term in evidence.casefold()
        for term in (
            "trastuzumab", "tamoksifen", "tamoxifen", "kemoterapi",
            "chemotherapy", "radyoterapi", "radiotherapy",
        )
    ):
        return "Özette belirtilen tedavi öyküsü kaynak maddesiyle karşılaştırıldı."
    if decision.kind == "unspecified":
        return "Maddenin türü net olmadığı için otomatik yorum yapılmadı."
    return decision.rationale


def screening_label(evaluation: TrialEvaluation) -> str:
    return _SCREENING_LABELS[evaluation.screening_status]


def criterion_kind_label(decision: CriterionEvaluation) -> str:
    return _KIND_LABELS[decision.kind]


def trial_display_title(title: str) -> str:
    normalized = title.casefold()
    if "her2-negative advanced breast cancer" in normalized:
        return "İleri evre HER2-negatif meme kanseri araştırması"
    if "advanced breast cancer" in normalized:
        return "İleri evre meme kanseri araştırması"
    if "breast cancer" in normalized:
        return "Meme kanseri araştırması"
    return "Klinik araştırma"
