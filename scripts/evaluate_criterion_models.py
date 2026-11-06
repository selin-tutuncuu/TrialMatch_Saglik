from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from trialmatch.criterion_classifier import NaiveBayesCriterionClassifier
from trialmatch.criteria import evaluate_criterion
from trialmatch.evaluation import criterion_accuracy, unknown_recall
from trialmatch.models import Criterion
from trialmatch.profile import extract_patient_profile


def load_examples() -> list[dict[str, str]]:
    cases = json.loads((ROOT / "data/synthetic_cases.json").read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "data/golden_criteria.json").read_text(encoding="utf-8"))
    summaries = {item["case_id"]: item["summary"] for item in cases}
    return [
        {**item, "summary": summaries[item["case_id"]]}
        for item in labels
    ]


def ollama_predict(
    client: httpx.Client,
    model: str,
    summary: str,
    criterion: str,
) -> tuple[str, int, int]:
    response = client.post(
        "http://127.0.0.1:11434/api/chat",
        json={
            "model": model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify the synthetic patient facts against one criterion. "
                        "Return JSON only with decision equal to MET, NOT_MET, or UNKNOWN. "
                        "Do not give medical advice. If evidence is insufficient, use UNKNOWN."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"synthetic_summary": summary, "criterion": criterion},
                        ensure_ascii=False,
                    ),
                },
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    answer = json.loads(payload["message"]["content"])
    decision = answer.get("decision")
    if decision not in {"MET", "NOT_MET", "UNKNOWN"}:
        raise ValueError(f"Ollama returned an unsupported decision: {decision!r}")
    return (
        decision,
        int(payload.get("prompt_eval_count", 0)),
        int(payload.get("eval_count", 0)),
    )


def leave_one_case_out(examples: list[dict[str, str]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for example in examples:
        grouped[example["case_id"]].append(example)

    expected: list[str] = []
    predicted: list[str] = []
    rows = []
    started = time.perf_counter()
    for case_id, held_out in grouped.items():
        training = [item for key, items in grouped.items() if key != case_id for item in items]
        classifier = NaiveBayesCriterionClassifier()
        classifier.fit(training)
        for item in held_out:
            guess = classifier.predict(item["summary"], item["criterion"])
            expected.append(item["expected"])
            predicted.append(guess)
            rows.append(
                {
                    "case_id": case_id,
                    "criterion": item["criterion"],
                    "expected": item["expected"],
                    "predicted": guess,
                }
            )
    return {
        "accuracy": criterion_accuracy(expected, predicted),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "estimated_tokens": 0,
        "estimated_cost_usd": 0.0,
        "per_example": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare rules and a tiny classifier using synthetic labels only."
    )
    parser.add_argument("--ollama-model", help="Optional locally installed Ollama model name.")
    parser.add_argument(
        "--save-model",
        type=Path,
        default=ROOT / "data/models/criterion_naive_bayes.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/criterion_model_comparison.json",
    )
    args = parser.parse_args()

    examples = load_examples()
    rule_started = time.perf_counter()
    rule_evaluations = [
        evaluate_criterion(
            Criterion(kind=item["kind"], text=item["criterion"]),
            extract_patient_profile(item["summary"]),
        )
        for item in examples
    ]
    expected_decisions = [item["expected"] for item in examples]
    rule_predictions = [item.decision for item in rule_evaluations]
    determinate = [
        (item, evaluation)
        for item, evaluation in zip(examples, rule_evaluations)
        if evaluation.decision != "UNKNOWN"
    ]
    unsupported_decisions = [
        item
        for item, evaluation in determinate
        if not evaluation.patient_evidence
        or evaluation.patient_evidence not in item["summary"]
    ]
    rule_result = {
        "accuracy": criterion_accuracy(expected_decisions, rule_predictions),
        "unknown_recall": unknown_recall(expected_decisions, rule_predictions),
        "evidence_audit": {
            "determinate_decisions": len(determinate),
            "decisions_with_evidence_in_summary": len(determinate) - len(unsupported_decisions),
            "unsupported_decisions": len(unsupported_decisions),
            "unsupported_decision_rate": (
                len(unsupported_decisions) / len(determinate) if determinate else 0.0
            ),
            "scope": "synthetic rule-evaluator output; not an independent clinical audit",
        },
        "elapsed_seconds": round(time.perf_counter() - rule_started, 4),
        "estimated_tokens": 0,
        "estimated_cost_usd": 0.0,
        "per_example": [
            {
                "case_id": item["case_id"],
                "criterion": item["criterion"],
                "expected": item["expected"],
                "predicted": evaluation.decision,
                "patient_evidence": evaluation.patient_evidence,
            }
            for item, evaluation in zip(examples, rule_evaluations)
        ],
    }

    classifier = NaiveBayesCriterionClassifier()
    classifier.fit(examples)
    args.save_model.parent.mkdir(parents=True, exist_ok=True)
    args.save_model.write_text(
        json.dumps(
            {
                "training_data": "synthetic_cases.json + golden_criteria.json",
                "labels": dict(classifier.class_counts),
                "token_counts": {
                    label: dict(counts)
                    for label, counts in classifier.token_counts.items()
                },
                "total_tokens": dict(classifier.total_tokens),
                "vocabulary": sorted(classifier.vocabulary),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result: dict[str, Any] = {
        "data": "synthetic only; not clinically validated",
        "examples": len(examples),
        "rule_baseline": rule_result,
        "naive_bayes_leave_one_case_out": leave_one_case_out(examples),
        "naive_bayes_trained_model": str(args.save_model),
        "llm_baseline": {
            "status": "not run",
            "reason": "No LLM is called unless a local Ollama model is explicitly selected.",
        },
    }
    if args.ollama_model:
        predictions = []
        input_tokens = 0
        output_tokens = 0
        started = time.perf_counter()
        with httpx.Client() as client:
            for item in examples:
                decision, prompt_count, completion_count = ollama_predict(
                    client,
                    args.ollama_model,
                    item["summary"],
                    item["criterion"],
                )
                predictions.append(decision)
                input_tokens += prompt_count
                output_tokens += completion_count
        result["llm_baseline"] = {
            "provider": "local Ollama",
            "model": args.ollama_model,
            "accuracy": criterion_accuracy(
                [item["expected"] for item in examples], predictions
            ),
            "elapsed_seconds": round(time.perf_counter() - started, 4),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": 0.0,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
