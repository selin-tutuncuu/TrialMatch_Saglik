import json
from pathlib import Path

import pytest

from trialmatch.agents import DISCLAIMER, EligibilityAgent, SafetyCriticAgent, TrialMatchOrchestrator
from trialmatch.models import CriterionEvaluation, PatientProfile, TrialEvaluation, TrialSummary
from trialmatch.reporting import save_report

ROOT = Path(__file__).resolve().parents[1]
SECURITY = json.loads((ROOT / "data/security_tests.json").read_text(encoding="utf-8"))


class FakeSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.trial = TrialSummary(
            nct_id="NCT01234567",
            title="Fictional recruiting study",
            status="RECRUITING",
            eligibility_criteria=(
                "Inclusion Criteria:\n"
                "- Age at least 18 years.\n"
                "- HER2-positive disease.\n"
                "- Female participants.\n"
                "Exclusion Criteria:\n"
                "- Active brain metastases."
            ),
            source_url="https://clinicaltrials.gov/study/NCT01234567",
            fetched_at="2026-01-01T00:00:00Z",
        )

    def search_and_fetch(self, condition: str, location: str | None = None, age: int | None = None, sex: str = "unknown", limit: int = 20) -> list[TrialSummary]:
        self.calls.append({"condition": condition, "location": location, "age": age, "sex": sex})
        return [self.trial] if condition == "breast cancer" else []


def orchestrator(tmp_path: Path, fake: FakeSearch) -> TrialMatchOrchestrator:
    return TrialMatchOrchestrator(
        search_client=fake,
        log_path=tmp_path / "audit.jsonl",
        trace_path=tmp_path / "traces.jsonl",
    )


def test_successful_report_has_citations_unknowns_and_safety_text(tmp_path: Path) -> None:
    fake = FakeSearch()
    report = orchestrator(tmp_path, fake).run(
        "54 yaş kadın, meme kanseri, evre IIIA, HER2 pozitif. İstanbul."
    )
    assert not report.rejected
    assert report.disclaimer == DISCLAIMER
    assert len(report.trials) == 1
    evaluations = report.trials[0].criteria
    assert all(item.criterion_quote in fake.trial.eligibility_criteria for item in evaluations)
    assert {item.decision for item in evaluations} >= {"MET", "UNKNOWN"}
    assert any(item.decision == "UNKNOWN" for item in evaluations)
    assert not any("uygunsunuz" in item.lower() for item in report.warnings)


@pytest.mark.parametrize("query", SECURITY["out_of_scope"])
def test_medical_advice_requests_are_refused(query: str, tmp_path: Path) -> None:
    fake = FakeSearch()
    report = orchestrator(tmp_path, fake).run(query)
    assert report.rejected
    assert report.refusal_reason
    assert not fake.calls


@pytest.mark.parametrize("injection", SECURITY["prompt_injection"])
def test_instruction_like_text_never_overrides_profile(injection: str, tmp_path: Path) -> None:
    baseline_search = FakeSearch()
    injected_search = FakeSearch()
    baseline = orchestrator(tmp_path / "base", baseline_search).run(
        "54 yaş kadın, meme kanseri, HER2 pozitif."
    )
    injected = orchestrator(tmp_path / "injected", injected_search).run(
        f"54 yaş kadın, meme kanseri, HER2 pozitif. {injection}"
    )
    if injected.rejected:
        assert not injected_search.calls
        assert baseline.trials
        return
    assert [item.decision for item in baseline.trials[0].criteria] == [
        item.decision for item in injected.trials[0].criteria
    ]
    assert injected.profile.age == baseline.profile.age
    assert injected.profile.sex == baseline.profile.sex
    assert injected.warnings


def test_logs_do_not_contain_raw_input_or_common_pii(tmp_path: Path) -> None:
    fake = FakeSearch()
    raw = "Hasta: Ayşe Yılmaz, 54 yaş kadın, meme kanseri, TC 11111111111."
    orchestrator(tmp_path, fake).run(raw)
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "Ayşe Yılmaz" not in log
    assert "11111111111" not in log
    assert raw not in log
    assert "national_id" in log
    traces = (tmp_path / "traces.jsonl").read_text(encoding="utf-8")
    assert "54 yaş" not in traces
    assert "duration_ms" in traces
    assert '"input_tokens": 0' in traces
    assert '"cost_usd": 0.0' in traces


def test_pii_is_redacted_before_any_search_tool_call(tmp_path: Path) -> None:
    fake = FakeSearch()
    report = orchestrator(tmp_path, fake).run(
        "Hasta: Ayşe Yılmaz, 54 yaş kadın, meme kanseri, HER2 pozitif, TC 11111111111."
    )
    assert not report.rejected
    assert len(fake.calls) == 1
    assert fake.calls[0]["condition"] == "breast cancer"


def test_save_requires_explicit_human_approval(tmp_path: Path) -> None:
    report = orchestrator(tmp_path, FakeSearch()).run(
        "54 yaş kadın, meme kanseri, HER2 pozitif."
    )
    with pytest.raises(PermissionError):
        save_report(report, approved=False, output_dir=tmp_path / "reports")
    path = save_report(report, approved=True, output_dir=tmp_path / "reports")
    assert path.exists()
    assert DISCLAIMER in path.read_text(encoding="utf-8")


def test_safety_critic_catches_uncited_decision_and_certainty_language() -> None:
    fake = FakeSearch()
    malformed = TrialEvaluation(
        trial=fake.trial,
        criteria=[
            CriterionEvaluation(
                kind="inclusion",
                decision="MET",
                criterion_quote="Not a source quote",
                patient_evidence=None,
                rationale="Patient uygunsunuz.",
            )
        ],
        screening_status="possible_match_for_clinician_review",
        score=1,
        unknown_count=0,
    )
    issues = SafetyCriticAgent().verify(
        [malformed],
        original_trial_ids=set(),
        sanitized_text="54 years old",
        profile=PatientProfile(),
    )
    assert any("kriter alıntısı" in issue for issue in issues)
    assert any("kesin uygunluk" in issue for issue in issues)
    assert any("çalışma kimliği" in issue for issue in issues)
    assert any("kanıt" in issue for issue in issues)


def test_orchestrator_rewrites_unsafe_rationale_to_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsafe_evaluation(
        _agent: EligibilityAgent,
        trial: TrialSummary,
        profile: PatientProfile,
    ) -> TrialEvaluation:
        evidence = profile.source_spans["age"]
        return TrialEvaluation(
            trial=trial,
            criteria=[
                CriterionEvaluation(
                    kind="inclusion",
                    decision="MET",
                    criterion_quote="Age at least 18 years.",
                    patient_evidence=evidence,
                    rationale="The patient is eligible.",
                )
            ],
            screening_status="possible_match_for_clinician_review",
            score=1,
            unknown_count=0,
        )

    monkeypatch.setattr(EligibilityAgent, "run", unsafe_evaluation)
    report = orchestrator(tmp_path, FakeSearch()).run(
        "54 yaş kadın, meme kanseri."
    )
    assert report.trials[0].criteria[0].decision == "UNKNOWN"
    assert "eligible" not in report.trials[0].criteria[0].rationale
    assert any("Güvenlik denetimi" in warning for warning in report.warnings)


def test_unmaskable_pii_stops_before_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("trialmatch.agents.contains_unmasked_common_pii", lambda _: True)
    fake = FakeSearch()
    report = orchestrator(tmp_path, fake).run("fictional case")
    assert report.rejected
    assert "maskelenemedi" in report.refusal_reason
    assert not fake.calls
