from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Sex = Literal["female", "male", "unknown"]
CriterionType = Literal["inclusion", "exclusion", "unspecified"]
Decision = Literal["MET", "NOT_MET", "UNKNOWN"]


class Biomarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str | None = None
    source_span: str | None = None


class PatientProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis: str | None = None
    stage: str | None = None
    age: int | None = Field(default=None, ge=0, le=120)
    sex: Sex = "unknown"
    biomarkers: list[Biomarker] = Field(default_factory=list)
    prior_treatments: list[str] = Field(default_factory=list)
    treatment_history_negatives: list[str] = Field(default_factory=list)
    comorbidities: list[str] = Field(default_factory=list)
    ecog: int | None = Field(default=None, ge=0, le=5)
    location: str | None = None
    source_spans: dict[str, str] = Field(default_factory=dict)


class TrialSummary(BaseModel):
    nct_id: str
    title: str
    status: str
    conditions: list[str] = Field(default_factory=list)
    brief_summary: str | None = None
    eligibility_criteria: str | None = None
    sex: str | None = None
    minimum_age: str | None = None
    maximum_age: str | None = None
    locations: list[str] = Field(default_factory=list)
    nearest_location: str | None = None
    distance_km: float | None = None
    source_url: str
    fetched_at: str


class Criterion(BaseModel):
    kind: CriterionType
    text: str


class CriterionEvaluation(BaseModel):
    kind: CriterionType
    decision: Decision
    criterion_quote: str
    patient_evidence: str | None = None
    rationale: str


class TrialEvaluation(BaseModel):
    trial: TrialSummary
    criteria: list[CriterionEvaluation]
    screening_status: Literal[
        "possible_match_for_clinician_review",
        "needs_more_information",
        "does_not_appear_to_meet",
    ]
    score: float
    unknown_count: int
    missing_information: list[str] = Field(default_factory=list)


class PrescreenReport(BaseModel):
    disclaimer: str
    closing_disclaimer: str = (
        "Bu bir karar destek çıktısıdır; tanı veya tedavi önerisi değildir. "
        "Son karar hekimindir."
    )
    generated_at: str
    profile: PatientProfile
    trials: list[TrialEvaluation]
    warnings: list[str] = Field(default_factory=list)
    patient_explanation: str | None = None
    readability_score: float | None = Field(default=None, ge=0, le=100)
    rejected: bool = False
    refusal_reason: str | None = None
    audit_id: str
