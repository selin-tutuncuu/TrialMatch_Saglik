from __future__ import annotations

import re
import unicodedata
import json
from functools import lru_cache
from pathlib import Path

from trialmatch.models import (
    Criterion,
    CriterionEvaluation,
    PatientProfile,
    TrialSummary,
)

_HEADER = re.compile(
    r"^\s*(inclusion|exclusion)\s+criteria\s*:?\s*$",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_AGE_RANGE = re.compile(r"\b(?:aged?\s*)?(\d{1,3})\s*(?:to|-|through)\s*(\d{1,3})\s*(?:years?|yaş)?")
_AGE_MIN = re.compile(
    r"\b(?:at least|minimum(?: age)? of|older than|aged?\s+|age\s+|"
    r"yaşında veya üzerinde|en az|en küçük|≥)\s*(\d{1,3})\s*(?:years?|yaş)?",
    re.IGNORECASE,
)
_AGE_MIN_POSTFIX = re.compile(r"\b(\d{1,3})\s*years?\s+(?:and\s+)?older\b", re.IGNORECASE)
_AGE_MAX = re.compile(
    r"\b(?:up to|no older than|maximum(?: age)? of|under|at most|"
    r"en fazla|yaşından küçük|≤)\s*(\d{1,3})\s*(?:years?|yaş)?",
    re.IGNORECASE,
)
_STAGE = re.compile(r"\b(?:stage|evre)\s*(iv|iii|ii|i|4|3|2|1)", re.IGNORECASE)
_KNOWLEDGE_GRAPH_PATH = Path(__file__).resolve().parent.parent / "data" / "clinical_knowledge_graph.json"


@lru_cache(maxsize=1)
def _clinical_knowledge_graph() -> dict[str, list[dict[str, str]]]:
    return json.loads(_KNOWLEDGE_GRAPH_PATH.read_text(encoding="utf-8"))


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def split_eligibility_criteria(text: str | None) -> list[Criterion]:
    if not text or not text.strip():
        return []
    current: str | None = None
    criteria: list[Criterion] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _HEADER.match(line.rstrip(":"))
        if heading:
            current = heading.group(1).casefold()
            continue
        line = _BULLET.sub("", line).strip()
        if not line or len(line) < 3:
            continue
        kind = current if current in {"inclusion", "exclusion"} else "unspecified"
        for fragment in re.split(r"(?<=[.;])\s+(?=[A-ZÇĞİÖŞÜ0-9])", line):
            fragment = fragment.strip()
            if len(fragment) >= 3:
                criteria.append(Criterion(kind=kind, text=fragment))
    return criteria


def evaluate_criterion(criterion: Criterion, profile: PatientProfile) -> CriterionEvaluation:
    quote = criterion.text
    normalized = _clean(quote)
    requires_prior_treatment = bool(
        re.search(
            r"\b(?:prior|previous|received|history of|önceki|almış|kullanmış)\b",
            normalized,
        )
    )
    evidence: str | None = None
    decision = "UNKNOWN"
    rationale = "Vaka özetinde bu maddeyi değerlendirmeye yetecek açık bilgi bulunmuyor."

    age_source = profile.source_spans.get("age")
    if "age" in normalized or "year" in normalized or "yaş" in normalized:
        if profile.age is not None:
            age_range = _AGE_RANGE.search(normalized)
            minimum = _AGE_MIN.search(normalized)
            minimum_postfix = _AGE_MIN_POSTFIX.search(normalized)
            maximum = _AGE_MAX.search(normalized)
            if age_range:
                lower, upper = int(age_range.group(1)), int(age_range.group(2))
                if lower <= profile.age <= upper:
                    decision, evidence = "MET", age_source
                    rationale = "Özette bildirilen yaş, kaynakta belirtilen aralıkta."
                else:
                    decision, evidence = "NOT_MET", age_source
                    rationale = "Özette bildirilen yaş, kaynakta belirtilen aralığın dışında."
            elif (minimum or minimum_postfix) and profile.age < int((minimum or minimum_postfix).group(1)):
                decision, evidence = "NOT_MET", age_source
                rationale = "Özette bildirilen yaş, kaynakta belirtilen alt sınırın altında."
            elif maximum and profile.age > int(maximum.group(1)):
                decision, evidence = "NOT_MET", age_source
                rationale = "Özette bildirilen yaş, kaynakta belirtilen üst sınırın üzerinde."
            elif minimum or minimum_postfix or maximum:
                decision, evidence = "MET", age_source
                rationale = "Özette bildirilen yaş, kaynakta belirtilen sayısal eşiği karşılıyor."

    if decision == "UNKNOWN" and ("stage" in normalized or "evre" in normalized):
        stage_source = profile.source_spans.get("stage")
        requested = _STAGE.search(normalized)
        reported = _STAGE.search(_clean(stage_source or ""))
        if requested and reported:
            roman_values = {
                "i": 1, "ii": 2, "iii": 3, "iv": 4,
                "1": 1, "2": 2, "3": 3, "4": 4,
            }
            matches = roman_values[requested.group(1).casefold()] == roman_values[reported.group(1).casefold()]
            decision = "MET" if matches else "NOT_MET"
            evidence = stage_source
            rationale = "Özette bildirilen evre, kaynak maddesindeki evreyle eşleşiyor." if matches else "Özette bildirilen evre, kaynak maddesindeki evreden farklı."

    if decision == "UNKNOWN" and any(term in normalized for term in ("female", "women", "woman", "male", "men", "man", "sex", "gender", "kadın", "erkek")):
        if profile.sex != "unknown":
            words = set(re.findall(r"\w+", normalized))
            wants_female = bool(words & {"female", "women", "woman", "kadın"})
            wants_male = bool(words & {"male", "men", "man", "erkek"})
            if wants_female or wants_male:
                matches = profile.sex == "female" and wants_female or profile.sex == "male" and wants_male
                decision = "MET" if matches else "NOT_MET"
                evidence = profile.source_spans.get("sex")
                rationale = "Özette bildirilen cinsiyet, kaynak maddesiyle eşleşiyor." if matches else "Özette bildirilen cinsiyet, kaynak maddesiyle çelişiyor."

    if decision == "UNKNOWN":
        for key, source in profile.source_spans.items():
            if requires_prior_treatment and key.startswith(
                ("biomarker:", "treatment_negative:")
            ):
                continue
            value = _clean(source)
            if len(value) >= 3 and value in normalized:
                decision, evidence = "MET", source
                rationale = "Kaynak maddede yer alan bilgi, vaka özetinde açıkça belirtilmiş."
                break

    if decision == "UNKNOWN":
        graph = _clinical_knowledge_graph()
        diagnosis = _clean(profile.diagnosis or "")
        disease_aliases = {
            _clean(item["subject"])
            for item in graph["relationships"]
            if item["predicate"] == "has_alias"
            and _clean(item["object"]) in diagnosis
        }
        disease_names = {diagnosis, *disease_aliases}
        for biomarker in profile.biomarkers:
            if requires_prior_treatment:
                continue
            biomarker_name = _clean(biomarker.name)
            biomarker_terms = {biomarker_name}
            linked_diseases = {
                _clean(item["object"])
                for item in graph["relationships"]
                if item["predicate"] == "biomarker_for"
                and _clean(item["subject"]) == biomarker_name
            }
            if linked_diseases and linked_diseases & disease_names:
                biomarker_terms.update(
                    _clean(item["object"])
                    for item in graph["relationships"]
                    if item["predicate"] == "has_alias"
                    and _clean(item["subject"]) == biomarker_name
                )
            if (
                any(
                    term
                    and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)
                    for term in biomarker_terms
                )
                and biomarker.source_span
            ):
                profile_value = _clean(biomarker.source_span)
                wants_positive = any(word in normalized for word in ("positive", "pozitif", "overexpress"))
                wants_negative = any(word in normalized for word in ("negative", "negatif", "absent"))
                profile_positive = any(word in profile_value for word in ("positive", "pozitif", "+"))
                profile_negative = any(word in profile_value for word in ("negative", "negatif", "-"))
                if wants_positive and profile_positive or wants_negative and profile_negative:
                    decision, evidence = "MET", biomarker.source_span
                    rationale = "Özette bildirilen biyobelirteç sonucu, kaynak maddesiyle eşleşiyor."
                elif wants_positive and profile_negative or wants_negative and profile_positive:
                    decision, evidence = "NOT_MET", biomarker.source_span
                    rationale = "Özette bildirilen biyobelirteç sonucu, kaynak maddesiyle çelişiyor."
                elif not wants_positive and not wants_negative:
                    decision, evidence = "MET", biomarker.source_span
                    rationale = "Bu biyobelirteç özette açıkça belirtilmiş; klinik anlamı ayrıca doğrulanmalı."
                break

    if decision == "UNKNOWN":
        if requires_prior_treatment and (
            profile.prior_treatments or profile.treatment_history_negatives
        ):
            graph = _clinical_knowledge_graph()
            treatment_classes = {
                _clean(item["subject"]): _clean(item["object"])
                for item in graph["relationships"]
                if item["predicate"] == "is_a"
            }
            criterion_terms = set(re.findall(r"\w+", normalized))
            for treatment in profile.treatment_history_negatives:
                normalized_treatment = _clean(treatment)
                treatment_class = treatment_classes.get(normalized_treatment)
                if (
                    normalized_treatment in normalized
                    or (
                        treatment_class
                        and set(re.findall(r"\w+", treatment_class)).issubset(criterion_terms)
                    )
                ):
                    evidence = next(
                        (
                            source
                            for key, source in profile.source_spans.items()
                            if key.startswith("treatment_negative:")
                            and _clean(source) == normalized_treatment
                        ),
                        None,
                    )
                    if evidence:
                        decision = "NOT_MET"
                        rationale = "Vaka özetinde bu tedavinin daha önce alınmadığı açıkça belirtilmiş."
                        break
            for treatment in profile.prior_treatments:
                if decision != "UNKNOWN":
                    break
                normalized_treatment = _clean(treatment)
                treatment_class = treatment_classes.get(normalized_treatment)
                if (
                    normalized_treatment in normalized
                    or (
                        treatment_class
                        and set(re.findall(r"\w+", treatment_class)).issubset(criterion_terms)
                    )
                ):
                    evidence = next(
                        (
                            source
                            for key, source in profile.source_spans.items()
                            if key.startswith("prior_treatment:")
                            and _clean(source) == normalized_treatment
                        ),
                        None,
                    )
                    if evidence:
                        decision = "MET"
                        rationale = "Özette bildirilen önceki tedavi, yerel terim eşlemesiyle bu maddeyle ilişkilendirildi."
                        break

    return CriterionEvaluation(
        kind=criterion.kind,
        decision=decision,
        criterion_quote=quote,
        patient_evidence=evidence if evidence and evidence in " ".join(profile.source_spans.values()) else None,
        rationale=rationale,
    )


def evaluate_trial(trial: TrialSummary, profile: PatientProfile) -> list[CriterionEvaluation]:
    criteria = split_eligibility_criteria(trial.eligibility_criteria)
    return [evaluate_criterion(criterion, profile) for criterion in criteria]


def rank_trial_evaluations(
    trials: list[TrialSummary],
    profile: PatientProfile,
) -> list[tuple[TrialSummary, list[CriterionEvaluation], str, float, list[str]]]:
    ranked = []
    for trial in trials:
        decisions = evaluate_trial(trial, profile)
        blocked = any(
            (item.kind == "inclusion" and item.decision == "NOT_MET")
            or (item.kind == "exclusion" and item.decision == "MET")
            for item in decisions
        )
        unknown = [item.criterion_quote for item in decisions if item.decision == "UNKNOWN"]
        inclusions = [item for item in decisions if item.kind == "inclusion"]
        met = sum(item.decision == "MET" for item in inclusions)
        score = met / len(inclusions) if inclusions else 0.0
        status = (
            "does_not_appear_to_meet" if blocked else
            "needs_more_information" if unknown or not decisions else
            "possible_match_for_clinician_review"
        )
        ranked.append((trial, decisions, status, score, unknown))
    ranked.sort(
        key=lambda item: (
            item[2] == "does_not_appear_to_meet",
            -item[3],
            len(item[4]),
            item[0].nct_id,
        )
    )
    return ranked
