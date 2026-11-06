from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from trialmatch.criteria import split_eligibility_criteria
from trialmatch.mcp_client import ClinicalTrialsMCPClient
from trialmatch.models import (
    PatientProfile,
    PrescreenReport,
    TrialEvaluation,
    TrialSummary,
)
from trialmatch.privacy import contains_unmasked_common_pii, redact_pii
from trialmatch.profile import extract_patient_profile
from trialmatch.plain_language import explain_results, readability_score
from trialmatch.retrieval import CriteriaRetriever, map_terms
from trialmatch.tracing import configure_phoenix_tracer

DISCLAIMER = (
    "Bu bir karar destek çıktısıdır; tanı veya tedavi önerisi değildir. "
    "Son karar hekimindir."
)
PUBLIC_WARNING = (
    "Gerçek hasta bilgisi girmeyin. Bu araç eğitim amaçlı bir karar destek "
    "prototipidir; tanı ya da tedavi önermez."
)
REFUSAL = (
    "TrialMatch tanı, tedavi, ilaç/doz veya hastalığın seyri hakkında öneri vermez. "
    "Bu konuları hastanın hekimiyle görüşün."
)
_ADVICE = re.compile(
    r"\b(?:hangi|ne)\s+(?:ila[cç]\w*|kemoterapi\w*|dozu|tedaviyi)\b|"
    r"\b(?:ila[cç]\s+doz\w*|ameliyat olmalı|iyileşir mi|prognoz\w*|doz öner)\b|"
    r"\b(?:what treatment|which drug|what dose|will (?:the patient )?recover)\b",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"(ignore previous|önceki talimatları yok say|sistem\s*:|developer mode|"
    r"geliştirici mod|hepsini met yaz|all criteria.*eligible|"
    r"uyarı metnini kaldır|onay isteme)",
    re.IGNORECASE,
)
_FORBIDDEN_CERTAINTY = re.compile(
    r"\b(?:uygunsunuz|uygun değilsiniz|kesinlikle uygundur|kesinlikle uygun|"
    r"katılabilirsiniz|eligible|ineligible)\b",
    re.IGNORECASE,
)


class TrialSearch(Protocol):
    def search_and_fetch(
        self,
        condition: str,
        location: str | None = None,
        age: int | None = None,
        sex: str = "unknown",
        limit: int = 20,
    ) -> list[TrialSummary]: ...


class IntakePIIGuardAgent:
    def run(self, raw_text: str) -> tuple[str, tuple[str, ...]]:
        result = redact_pii(raw_text)
        if contains_unmasked_common_pii(result.text):
            raise PrivacyGuardError(
                "PII could not be fully masked; the request was stopped before processing."
            )
        return result.text, result.pii_types


class PrivacyGuardError(ValueError):
    """Raised when detected personal information cannot be reliably masked."""


class ProfileExtractorAgent:
    def run(self, sanitized_text: str) -> PatientProfile:
        return extract_patient_profile(sanitized_text)


class TrialSearchAgent:
    def __init__(
        self,
        client: TrialSearch,
        lexicon_path: Path | None = None,
    ) -> None:
        self.client = client
        self.lexicon_path = lexicon_path or Path("data/term_lexicon.json")

    def run(self, profile: PatientProfile, limit: int) -> list[TrialSummary]:
        if not profile.diagnosis:
            return []
        translated = map_terms(
            profile.diagnosis,
            direction="tr→en",
            lexicon_path=self.lexicon_path,
        )
        queries = list(dict.fromkeys([*translated, profile.diagnosis]))
        for condition in queries:
            trials = self.client.search_and_fetch(
                condition=condition,
                location=profile.location,
                age=profile.age,
                sex=profile.sex,
                limit=limit,
            )
            if trials:
                return trials
        return []


class EligibilityAgent:
    def __init__(self, retriever: CriteriaRetriever) -> None:
        self.retriever = retriever

    def run(self, trial: TrialSummary, profile: PatientProfile) -> TrialEvaluation:
        all_criteria = split_eligibility_criteria(trial.eligibility_criteria)
        query = " ".join(
            part for part in (
                profile.diagnosis or "",
                profile.stage or "",
                " ".join(item.source_span or item.name for item in profile.biomarkers),
            ) if part
        )
        retrieved = self.retriever.retrieve(query, all_criteria)
        retrieved_text = {item.text for item in retrieved}
        ordered = [item for item in all_criteria if item.text in retrieved_text]
        ordered.extend(item for item in all_criteria if item.text not in retrieved_text)

        # Evaluation is deliberately conservative and rule-based. No criterion
        # is dropped when retrieval returns only a subset.
        from trialmatch.criteria import evaluate_criterion

        decisions = []
        for item in ordered:
            decision = evaluate_criterion(item, profile)
            if item.kind == "unspecified" and decision.decision != "UNKNOWN":
                decision.decision = "UNKNOWN"
                decision.patient_evidence = None
                decision.rationale = "Bu maddenin dahil etme mi dışlama mı olduğu net ayrıştırılamadı; uzman incelemesi gerekli."
            decisions.append(decision)
        blocked = any(
            (item.kind == "inclusion" and item.decision == "NOT_MET")
            or (item.kind == "exclusion" and item.decision == "MET")
            for item in decisions
        )
        missing = [item.criterion_quote for item in decisions if item.decision == "UNKNOWN"]
        if not all_criteria:
            missing.append("Kaynak kayıtta çalışma kriterleri bulunmuyor.")
        inclusions = [item for item in decisions if item.kind == "inclusion"]
        score = sum(item.decision == "MET" for item in inclusions) / len(inclusions) if inclusions else 0.0
        status = (
            "does_not_appear_to_meet" if blocked else
            "needs_more_information" if missing or not decisions else
            "possible_match_for_clinician_review"
        )
        return TrialEvaluation(
            trial=trial,
            criteria=decisions,
            screening_status=status,
            score=score,
            unknown_count=len(missing),
            missing_information=missing,
        )


class ReportAgent:
    def run(
        self,
        evaluations: list[TrialEvaluation],
        limit: int,
    ) -> list[TrialEvaluation]:
        return sorted(
            evaluations,
            key=lambda item: (
                item.screening_status == "does_not_appear_to_meet",
                item.trial.distance_km is None,
                item.trial.distance_km if item.trial.distance_km is not None else float("inf"),
                -item.score,
                item.unknown_count,
                item.trial.nct_id,
            ),
        )[:limit]


class SafetyCriticAgent:
    def verify(
        self,
        evaluations: list[TrialEvaluation],
        original_trial_ids: set[str],
        sanitized_text: str,
        profile: PatientProfile,
    ) -> list[str]:
        issues: list[str] = []
        allowed_evidence = set(profile.source_spans.values())
        for evaluation in evaluations:
            trial = evaluation.trial
            if trial.nct_id not in original_trial_ids:
                issues.append("Rapor, doğrulanmış kaynaktan gelmeyen bir çalışma kimliği içeriyor.")
            if not re.fullmatch(r"NCT\d{8}", trial.nct_id):
                issues.append("Rapor geçersiz bir çalışma kimliği içeriyor.")
            trial_text = trial.eligibility_criteria or ""
            for decision in evaluation.criteria:
                if decision.criterion_quote not in trial_text:
                    issues.append("Bir kriter alıntısı kaynak metinle birebir eşleşmiyor.")
                if _FORBIDDEN_CERTAINTY.search(decision.rationale):
                    issues.append("Raporda kesin uygunluk bildiren yasaklı bir ifade var.")
                if decision.decision in {"MET", "NOT_MET"}:
                    if not decision.patient_evidence or decision.patient_evidence not in sanitized_text:
                        issues.append("Belirsiz olmayan bir kararda anonim vaka metninden kanıt yok.")
                    if decision.patient_evidence not in allowed_evidence:
                        issues.append("Bir karar, çıkarılan profilde bulunmayan kanıta dayanıyor.")
        return list(dict.fromkeys(issues))


class TrialMatchOrchestrator:
    max_steps = 20

    def __init__(
        self,
        search_client: TrialSearch | None = None,
        cache_dir: Path | None = None,
        log_path: Path | None = None,
        trace_path: Path | None = None,
        enable_embeddings: bool = False,
    ) -> None:
        root = Path(__file__).resolve().parent.parent
        self.cache_dir = cache_dir or Path("data/cache")
        self.intake = IntakePIIGuardAgent()
        self.profile_agent = ProfileExtractorAgent()
        self.search_agent = TrialSearchAgent(
            search_client or ClinicalTrialsMCPClient(root, cache_dir=self.cache_dir),
            lexicon_path=root / "data" / "term_lexicon.json",
        )
        self.eligibility_agent = EligibilityAgent(
            CriteriaRetriever(
                root / "data" / "term_lexicon.json",
                enable_embeddings=enable_embeddings,
                index_path=self.cache_dir / "criteria-index.json",
                model_name=os.getenv(
                    "TRIALMATCH_EMBEDDING_MODEL",
                    "intfloat/multilingual-e5-small",
                ),
                reranker_name=os.getenv("TRIALMATCH_RERANKER") or None,
            )
        )
        self.report_agent = ReportAgent()
        self.critic = SafetyCriticAgent()
        self.log_path = log_path or Path("data/cache/audit.jsonl")
        self.trace_path = trace_path or Path(
            os.getenv("TRIALMATCH_TRACE_PATH", "data/cache/traces.jsonl")
        )
        self.tracer = configure_phoenix_tracer(
            os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
        )

    def _audit(self, event: str, profile: PatientProfile | None = None, **details: object) -> str:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = profile.model_dump_json() if profile else "rejected"
        audit_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        safe_event = {
            "at": datetime.now(UTC).isoformat(),
            "audit_id": audit_id,
            "event": event,
            "details": details,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_event, ensure_ascii=False) + "\n")
        return audit_id

    def _trace(self, audit_id: str, step: str, started_at: float, **details: object) -> None:
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        safe_span = {
            "at": datetime.now(UTC).isoformat(),
            "trace_id": audit_id,
            "step": step,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "details": details,
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_span, ensure_ascii=False) + "\n")
        if self.tracer is not None:
            with self.tracer.start_as_current_span(step) as span:
                span.set_attribute("trialmatch.trace_id", audit_id)
                span.set_attribute("trialmatch.duration_ms", safe_span["duration_ms"])
                span.set_attribute("trialmatch.input_tokens", 0)
                span.set_attribute("trialmatch.output_tokens", 0)
                span.set_attribute("trialmatch.cost_usd", 0.0)
                for key, value in details.items():
                    if isinstance(value, (str, bool, int, float)):
                        span.set_attribute(f"trialmatch.{key}", value)

    def _rejected(self, reason: str, message: str = REFUSAL) -> PrescreenReport:
        audit_id = self._audit("request_rejected", reason=reason)
        return PrescreenReport(
            disclaimer=DISCLAIMER,
            generated_at=datetime.now(UTC).isoformat(),
            profile=PatientProfile(),
            trials=[],
            warnings=[DISCLAIMER],
            rejected=True,
            refusal_reason=message,
            audit_id=audit_id,
        )

    def run(self, raw_text: str, limit: int = 5) -> PrescreenReport:
        if self.tracer is None:
            return self._run(raw_text, limit)
        with self.tracer.start_as_current_span("trialmatch.prescreen") as span:
            span.set_attribute("trialmatch.workflow", "synthetic_prescreen")
            return self._run(raw_text, limit)

    def _run(self, raw_text: str, limit: int) -> PrescreenReport:
        if not raw_text.strip():
            return self._rejected("empty_input")
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10.")

        intake_started = time.perf_counter()
        try:
            sanitized_text, pii_types = self.intake.run(raw_text)
        except PrivacyGuardError:
            return self._rejected(
                "pii_not_masked",
                "Kişisel bilgi güvenli biçimde maskelenemedi; işlem durduruldu. "
                "Gerçek hasta verisi kullanmayın.",
            )
        suspicious = bool(_INJECTION.search(sanitized_text))
        self._audit(
            "intake_completed",
            pii_types=list(pii_types),
            suspicious_instruction_detected=suspicious,
            steps=1,
        )
        self._trace(
            hashlib.sha256(b"intake").hexdigest()[:16],
            "intake_pii_guard",
            intake_started,
            pii_types=list(pii_types),
        )
        if _ADVICE.search(sanitized_text):
            return self._rejected("medical_advice_request")

        profile_started = time.perf_counter()
        profile = self.profile_agent.run(sanitized_text)
        audit_id = self._audit(
            "profile_extracted",
            profile,
            fields_present=sorted(profile.source_spans),
            steps=2,
        )
        self._trace(
            audit_id,
            "profile_extraction",
            profile_started,
            extracted_field_count=len(profile.source_spans),
        )
        if not profile.diagnosis:
            return PrescreenReport(
                disclaimer=DISCLAIMER,
                generated_at=datetime.now(UTC).isoformat(),
                profile=profile,
                trials=[],
                warnings=[DISCLAIMER, "Tanı/araştırma alanı özetten çıkarılamadı; çalışma araması yapılmadı."],
                audit_id=audit_id,
            )

        search_started = time.perf_counter()
        trials = self.search_agent.run(profile, limit=limit)
        unique_trials = {trial.nct_id: trial for trial in trials}
        trials = list(unique_trials.values())
        self._trace(
            audit_id,
            "clinicaltrials_mcp_search_and_verification",
            search_started,
            returned_trial_count=len(trials),
        )
        evaluations: list[TrialEvaluation] = []
        steps = 3
        seen_queries: set[str] = set()
        for trial_index, trial in enumerate(trials):
            query_id = hashlib.sha256(trial.nct_id.encode("utf-8")).hexdigest()
            if query_id in seen_queries or steps >= self.max_steps:
                break
            seen_queries.add(query_id)
            evaluation_started = time.perf_counter()
            evaluations.append(self.eligibility_agent.run(trial, profile))
            self._trace(
                audit_id,
                "criterion_evaluation",
                evaluation_started,
                trial_ordinal=trial_index + 1,
                criterion_count=len(evaluations[-1].criteria),
            )
            steps += 1

        report_started = time.perf_counter()
        ranked = self.report_agent.run(evaluations, limit)
        issues = self.critic.verify(
            ranked,
            original_trial_ids=set(unique_trials),
            sanitized_text=sanitized_text,
            profile=profile,
        )
        self._trace(
            audit_id,
            "report_ranking_and_safety_critic",
            report_started,
            report_count=len(ranked),
            safety_issue_count=len(issues),
        )
        safety_corrections = 0
        if issues:
            safe_ranked: list[TrialEvaluation] = []
            verified_ids = set(unique_trials)
            for evaluation in ranked:
                trial = evaluation.trial
                if (
                    trial.nct_id not in verified_ids
                    or not re.fullmatch(r"NCT\d{8}", trial.nct_id)
                ):
                    safety_corrections += 1
                    continue
                trial_text = trial.eligibility_criteria or ""
                changed = False
                allowed_evidence = set(profile.source_spans.values())
                for item in evaluation.criteria:
                    invalid_quote = item.criterion_quote not in trial_text
                    invalid_evidence = (
                        item.decision in {"MET", "NOT_MET"}
                        and (
                            not item.patient_evidence
                            or item.patient_evidence not in sanitized_text
                            or item.patient_evidence not in allowed_evidence
                        )
                    )
                    unsafe_language = bool(_FORBIDDEN_CERTAINTY.search(item.rationale))
                    if invalid_quote or invalid_evidence or unsafe_language:
                        item.decision = "UNKNOWN"
                        item.patient_evidence = None
                        item.rationale = (
                            "Güvenlik denetimi bu kararı doğrulayamadı; "
                            "uzman incelemesi gerekli."
                        )
                        changed = True
                if changed:
                    safety_corrections += 1
                    evaluation.unknown_count = sum(
                        item.decision == "UNKNOWN" for item in evaluation.criteria
                    )
                    evaluation.missing_information = [
                        item.criterion_quote
                        for item in evaluation.criteria
                        if item.decision == "UNKNOWN"
                    ]
                    inclusions = [
                        item
                        for item in evaluation.criteria
                        if item.kind == "inclusion"
                    ]
                    evaluation.score = (
                        sum(item.decision == "MET" for item in inclusions)
                        / len(inclusions)
                        if inclusions else 0.0
                    )
                    blocked = any(
                        (
                            item.kind == "inclusion"
                            and item.decision == "NOT_MET"
                        )
                        or (
                            item.kind == "exclusion"
                            and item.decision == "MET"
                        )
                        for item in evaluation.criteria
                    )
                    evaluation.screening_status = (
                        "does_not_appear_to_meet"
                        if blocked else "needs_more_information"
                    )
                safe_ranked.append(evaluation)
            ranked = safe_ranked
            issues = self.critic.verify(
                ranked,
                original_trial_ids=verified_ids,
                sanitized_text=sanitized_text,
                profile=profile,
            )

        warning_list = [DISCLAIMER]
        if pii_types:
            warning_list.append(
                "Kişisel bilgi benzeri alanlar maskelendi; maske kontrol edilmeden hiçbir harici araca gönderilmedi."
            )
        if suspicious:
            warning_list.append(
                "Girdide talimat benzeri metin algılandı; klinik veri olarak işlendi ve talimat kabul edilmedi."
            )
        if safety_corrections:
            warning_list.append(
                "Güvenlik denetimi doğrulanamayan kararları UNKNOWN yaptı veya çalışma kaydını çıkardı."
            )
        if issues:
            ranked = []
            warning_list.append(
                "Güvenlik denetimi raporu doğrulayamadı; çalışmalar gösterilmedi."
            )
        if steps >= self.max_steps:
            warning_list.append("Arama tamamlanamadı: adım sınırına ulaşıldı; sonuçlar kısmi olabilir.")
        if not trials:
            warning_list.append(
                "Bu tanı, konum, yaş ve cinsiyet filtreleriyle Recruiting durumunda çalışma bulunamadı."
            )
        warning_list.extend(issues)
        explanation = explain_results(ranked)
        audit_id = self._audit(
            "prescreen_completed",
            profile,
            returned_trials=len(ranked),
            steps=steps,
            safety_issues=len(issues),
        )
        return PrescreenReport(
            disclaimer=DISCLAIMER,
            generated_at=datetime.now(UTC).isoformat(),
            profile=profile,
            trials=ranked,
            warnings=warning_list,
            audit_id=audit_id,
            patient_explanation=explanation,
            readability_score=readability_score(explanation),
        )
