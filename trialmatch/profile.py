from __future__ import annotations

import re

from trialmatch.models import Biomarker, PatientProfile

_BIOMARKERS = {
    "HER2": r"\bHER2(?:\s*(?:pozitif|positive|\+|negatif|negative|-))?",
    "ER": r"\bER(?!\w)(?:\s*(?:pozitif|positive|\+|negatif|negative|-))?",
    "PR": r"\bPR(?!\w)(?:\s*(?:pozitif|positive|\+|negatif|negative|-))?",
    "BRCA1": r"\bBRCA1(?:\s*(?:mutasyonu|mutasyon|mutation))?(?:\s*(?:pozitif|positive|\+|negatif|negative|-))?",
    "BRCA2": r"\bBRCA2(?:\s*(?:mutasyonu|mutasyon|mutation))?(?:\s*(?:pozitif|positive|\+|negatif|negative|-))?",
    "Ki-67": r"\bKi[- ]?67(?:\s*%?\s*\d+)?",
    "PD-L1": r"\bPD[- ]?L1(?:\s*(?:pozitif|positive|\+|negatif|negative|-))?",
    "HbA1c": r"\bHbA1c\s*%?\s*\d+(?:[.,]\d+)?%?",
    "eGFR": r"\beGFR\s*\d+(?:[.,]\d+)?",
}
_TREATMENTS = (
    "trastuzumab deruxtecan",
    "ado-trastuzumab emtansine",
    "trastuzumab",
    "pertuzumab",
    "tamoksifen",
    "tamoxifen",
    "letrozol",
    "letrozole",
    "anastrozol",
    "anastrozole",
    "eksemestan",
    "exemestane",
    "kemoterapi",
    "chemotherapy",
    "radyoterapi",
    "radiotherapy",
)


def _match(pattern: str, text: str) -> re.Match[str] | None:
    return re.search(pattern, text, re.IGNORECASE)


def extract_patient_profile(text: str) -> PatientProfile:
    """Conservative, rule-based extraction; absent facts remain null/unknown."""
    spans: dict[str, str] = {}
    age_match = _match(
        r"\b(\d{1,3})(?:\s*(?:yaş(?:ında)?|yo\b|y\.o\.)|"
        r"\s*-\s*years?[\s-]+old|\s+years?[\s-]+old)\b",
        text,
    )
    age = int(age_match.group(1)) if age_match and int(age_match.group(1)) <= 120 else None
    if age_match and age is not None:
        spans["age"] = age_match.group(0)

    female = _match(r"\b(?:kadın|female|woman)\b", text)
    male = _match(r"\b(?:erkek|male|man)\b", text)
    sex = "female" if female else "male" if male else "unknown"
    if female:
        spans["sex"] = female.group(0)
    elif male:
        spans["sex"] = male.group(0)

    diagnosis_match = _match(
        r"\b(?:meme kanseri|breast cancer|invaziv duktal karsinom|"
        r"ductal carcinoma|akciğer kanseri|lung cancer|tip\s*2 diyabet|"
        r"type\s*2 diabetes|kolorektal kanser|colorectal cancer|"
        r"over kanseri|ovarian cancer|prostat kanseri|prostate cancer|"
        r"anaplastic astrocytoma|astrocytoma|glioblastoma|burkitt(?:'s)? lymphoma|"
        r"lymphoma|aortic stenosis|heart failure|valvular disease|"
        r"carotid stenosis|c(?:\.|\s)?difficile|c diff(?:erential)? infection|"
        r"cirrhosis|hepatic encephalopathy|end.stage renal disease|"
        r"chronic kidney disease|kidney failure|stroke|intracranial hemorrhage|"
        r"diabetes(?: mellitus)?(?: type ii| type 2)?|dmii|dm2)\b",
        text,
    )
    diagnosis = diagnosis_match.group(0) if diagnosis_match else None
    if diagnosis_match:
        spans["diagnosis"] = diagnosis_match.group(0)

    stage_match = _match(r"\b(?:evre|stage)\s*(?:IV|III|II|I|4|3|2|1)(?:[A-C])?\b", text)
    stage = stage_match.group(0) if stage_match else None
    if stage_match:
        spans["stage"] = stage_match.group(0)

    biomarkers: list[Biomarker] = []
    for name, pattern in _BIOMARKERS.items():
        match = _match(pattern, text)
        if match:
            span = match.group(0)
            biomarkers.append(
                Biomarker(name=name, value=span[len(name) :].strip(" :-") or None, source_span=span)
            )
            spans[f"biomarker:{name}"] = span

    location_match = _match(
        r"\b(?:İstanbul|Ankara|İzmir|Bursa|Antalya|Istanbul|Ankara|Izmir|Bursa|Antalya)\b",
        text,
    )
    location = location_match.group(0) if location_match else None
    if location_match:
        spans["location"] = location_match.group(0)

    prior_treatments: list[str] = []
    treatment_history_negatives: list[str] = []
    treatment_spans: list[tuple[int, int]] = []
    for treatment in _TREATMENTS:
        treatment_match = _match(rf"(?<!\w){re.escape(treatment)}(?!\w)", text)
        if treatment_match:
            if any(
                treatment_match.start() < end and treatment_match.end() > start
                for start, end in treatment_spans
            ):
                continue
            treatment_spans.append((treatment_match.start(), treatment_match.end()))
            span = treatment_match.group(0)
            before = text[max(0, treatment_match.start() - 24):treatment_match.start()]
            before_phrase = re.split(r"[,;]", before)[-1]
            after = text[treatment_match.end():treatment_match.end() + 24]
            negated = bool(
                re.search(
                    r"\b(?:never|no|without|not|hasn't|hadn't|didn't|hiç)\b[^.!?]*$",
                    before_phrase,
                    re.I,
                )
                or re.match(
                    r"\s*(?:not\s+received|never\s+received|has\s+not\s+received|"
                    r"did\s+not\s+receive|almamış|almadı|kullanmamış|kullanmadı)",
                    after,
                    re.I,
                )
            )
            if negated:
                treatment_history_negatives.append(span)
                spans[f"treatment_negative:{len(treatment_history_negatives)}"] = span
            elif span.casefold() not in {item.casefold() for item in prior_treatments}:
                prior_treatments.append(span)
                spans[f"prior_treatment:{len(prior_treatments)}"] = span

    return PatientProfile(
        diagnosis=diagnosis,
        stage=stage,
        age=age,
        sex=sex,
        biomarkers=biomarkers,
        prior_treatments=prior_treatments,
        treatment_history_negatives=treatment_history_negatives,
        location=location,
        source_spans=spans,
    )
