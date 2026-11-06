from __future__ import annotations

import re

from trialmatch.models import TrialEvaluation


def readability_score(text: str) -> float:
    """Return a Turkish Ateşman readability estimate in the conventional 0–100 range."""
    words = re.findall(r"\b[\wçğıöşüÇĞİÖŞÜ-]+\b", text, re.IGNORECASE)
    if not words:
        return 0.0
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    syllables = sum(
        max(1, len(re.findall(r"[aeıioöuü]", word.casefold())))
        for word in words
    )
    score = 198.825 - 40.175 * (syllables / len(words)) - 2.610 * (len(words) / sentences)
    return round(max(0.0, min(100.0, score)), 1)


def explain_results(evaluations: list[TrialEvaluation]) -> str:
    if not evaluations:
        return (
            "Bu aramada gösterilecek çalışma bulunamadı. "
            "Bu sonuç bir kabul veya ret kararı değildir; hekimle görüşün."
        )
    possible = sum(
        item.screening_status == "possible_match_for_clinician_review"
        for item in evaluations
    )
    needs_info = sum(
        item.screening_status == "needs_more_information"
        for item in evaluations
    )
    does_not_appear = sum(
        item.screening_status == "does_not_appear_to_meet"
        for item in evaluations
    )
    parts = [
        f"{len(evaluations)} çalışma incelendi.",
        f"{possible} çalışma uzman incelemesi için öncelikli görünüyor.",
        f"{needs_info} çalışma için ek bilgi gerekiyor.",
        f"{does_not_appear} çalışmada karşılanmayan maddeler olabilir.",
        "Bu bir kabul veya ret kararı değildir. Son değerlendirmeyi hekim ve çalışma ekibi yapmalıdır.",
    ]
    return " ".join(parts)
