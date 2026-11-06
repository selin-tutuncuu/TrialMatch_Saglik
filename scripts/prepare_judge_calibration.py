from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trialmatch.criteria import evaluate_criterion
from trialmatch.models import Criterion
from trialmatch.profile import extract_patient_profile


def main() -> None:
    cases = json.loads((ROOT / "data/synthetic_cases.json").read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "data/golden_criteria.json").read_text(encoding="utf-8"))
    summaries = {item["case_id"]: item["summary"] for item in cases}
    selected = []
    for case_id in summaries:
        selected.extend(
            [item for item in labels if item["case_id"] == case_id][:2]
        )
    examples = []
    for item in selected:
        summary = summaries[item["case_id"]]
        decision = evaluate_criterion(
            Criterion(kind=item["kind"], text=item["criterion"]),
            extract_patient_profile(summary),
        )
        examples.append(
            {
                "case_id": item["case_id"],
                "synthetic_summary": summary,
                "source_criteria": item["criterion"],
                "criterion_quote": decision.criterion_quote,
                "decision": decision.decision,
                "patient_evidence": decision.patient_evidence,
                "rationale": decision.rationale,
                "human_quote_consistency_1_to_5": None,
                "human_safety_language_1_to_5": None,
            }
        )
    destination = ROOT / "data/judge_calibration_template.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "data": "synthetic only",
                "instructions": (
                    "Independently fill both human scores (1–5) for every row "
                    "before running the local LLM judge."
                ),
                "examples": examples,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(destination)


if __name__ == "__main__":
    main()
