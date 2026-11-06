from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trialmatch.clinicaltrials import ClinicalTrialsClient
from trialmatch.evaluation import hallucination_rate, ndcg_at_10, precision_at_10
from scripts.run_trec_baselines import load_topic_files, run_evaluation

_NCT_ID = re.compile(r"NCT\d{8}", re.IGNORECASE)


def parse_nct_ids(content: str, limit: int = 10) -> list[str]:
    payload = json.loads(content)
    if not isinstance(payload, dict) or not isinstance(payload.get("nct_ids"), list):
        raise ValueError("B0 must return a JSON object with an nct_ids list.")
    identifiers = []
    for candidate in payload["nct_ids"]:
        if not isinstance(candidate, str):
            continue
        match = _NCT_ID.fullmatch(candidate.strip())
        if match:
            identifier = match.group().upper()
            if identifier not in identifiers:
                identifiers.append(identifier)
        if len(identifiers) == limit:
            break
    return identifiers


def query_b0(
    client: httpx.Client,
    model: str,
    topic: str,
) -> tuple[list[str], int, int]:
    response = client.post(
        "http://127.0.0.1:11434/api/chat",
        json={
            "model": model,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 256},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an ungrounded, tool-less baseline in a synthetic "
                        "educational retrieval experiment. You have no search tools "
                        "and no trial database. From internal model knowledge only, "
                        "suggest up to 10 NCT identifiers that may match the case. "
                        "Do not give medical advice. If you cannot recall any IDs, "
                        "return an empty list. Return JSON only as "
                        '{"nct_ids":["NCT01234567"]}.'
                    ),
                },
                {"role": "user", "content": topic},
            ],
        },
        timeout=180,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload.get("message", {}).get("content")
    if not isinstance(content, str):
        raise ValueError("Ollama response has no message content.")
    return (
        parse_nct_ids(content),
        int(payload.get("prompt_eval_count", 0)),
        int(payload.get("eval_count", 0)),
    )


def _per_topic_metrics(
    run: dict[str, list[str]],
    judgments_by_topic: dict[str, dict[str, int]],
) -> dict[str, float]:
    topic_ids = list(judgments_by_topic)
    if not topic_ids:
        return {"macro_P@10": 0.0, "macro_nDCG@10": 0.0}
    return {
        "macro_P@10": sum(
            precision_at_10(run.get(topic_id, []), judgments_by_topic[topic_id])
            for topic_id in topic_ids
        ) / len(topic_ids),
        "macro_nDCG@10": sum(
            ndcg_at_10(run.get(topic_id, []), judgments_by_topic[topic_id])
            for topic_id in topic_ids
        ) / len(topic_ids),
    }


def run_b0_evaluation(
    topic_data: dict[str, Any],
    model: str,
    output: Path,
) -> dict[str, Any]:
    lexicon = json.loads((ROOT / "data/term_lexicon.json").read_text(encoding="utf-8"))
    retrieval = run_evaluation(topic_data, lexicon)
    judgments_by_topic: dict[str, dict[str, int]] = {}
    for item in topic_data["qrels"]:
        judgments_by_topic.setdefault(item["query_id"], {})[item["doc_id"]] = int(
            item["relevance"]
        )

    b0_run: dict[str, list[str]] = {}
    input_tokens = 0
    output_tokens = 0
    generation_started = time.perf_counter()
    with httpx.Client() as client:
        for topic_id in topic_data["query_ids"]:
            ids, prompt_count, completion_count = query_b0(
                client,
                model,
                topic_data["topics"][topic_id],
            )
            b0_run[topic_id] = ids
            input_tokens += prompt_count
            output_tokens += completion_count
    generation_seconds = time.perf_counter() - generation_started

    api = ClinicalTrialsClient(
        cache_dir=ROOT / "data/cache",
        min_request_interval=2.0,
    )
    verified_cache: dict[str, bool] = {}
    not_found = []
    verification_started = time.perf_counter()
    for identifiers in b0_run.values():
        for identifier in identifiers:
            if identifier not in verified_cache:
                verified_cache[identifier] = api.get_trial(identifier) is not None
            if not verified_cache[identifier]:
                not_found.append(identifier)
    verification_seconds = time.perf_counter() - verification_started

    b0_ids = [identifier for ids in b0_run.values() for identifier in ids]
    b0_hallucination_rate = (
        hallucination_rate(
            b0_ids,
            {identifier for identifier, exists in verified_cache.items() if exists},
        )
        if b0_ids
        else None
    )
    systems = {}
    for name, run in (
        ("B0_toolless_llm", b0_run),
        ("B1_BM25", retrieval["B1"]["run"]),
        ("Final_reranked", retrieval["Final"]["run"]),
    ):
        metrics = _per_topic_metrics(run, judgments_by_topic)
        systems[name] = {
            **metrics,
            "suggested_nct_ids": sum(len(ids) for ids in run.values()),
            "nct_id_hallucination_rate": (
                b0_hallucination_rate if name == "B0_toolless_llm" else 0.0
            ),
            "hallucination_validation": (
                "ClinicalTrials.gov API v2; queried NCT IDs only"
                if name == "B0_toolless_llm"
                else "IDs originate from NCT-validated records in the official TREC snapshot"
            ),
            "run": run,
        }

    result = {
        "dataset": topic_data["dataset"],
        "topics": len(topic_data["query_ids"]),
        "model": model,
        "data": "TREC topic narratives; no user-supplied patient text",
        "nct_validation_date": datetime.now(UTC).date().isoformat(),
        "b0_nct_ids_suggested": len(b0_ids),
        "unique_b0_ids_checked": len(verified_cache),
        "b0_nct_ids_not_found_count": len(not_found),
        "b0_ids_not_found_by_clinicaltrials_api": sorted(set(not_found)),
        "b0_input_tokens": input_tokens,
        "b0_output_tokens": output_tokens,
        "b0_generation_seconds": round(generation_seconds, 4),
        "nct_verification_seconds": round(verification_seconds, 4),
        "elapsed_seconds": round(generation_seconds + verification_seconds, 4),
        "estimated_cost_usd": 0.0,
        "systems": systems,
        "per_topic": [
            {
                "query_id": topic_id,
                **{
                    name: {
                        "P@10": precision_at_10(run.get(topic_id, []), judgments),
                        "nDCG@10": ndcg_at_10(run.get(topic_id, []), judgments),
                    }
                    for name, run in (
                        ("B0_toolless_llm", b0_run),
                        ("B1_BM25", retrieval["B1"]["run"]),
                        ("Final_reranked", retrieval["Final"]["run"]),
                    )
                },
            }
            for topic_id, judgments in judgments_by_topic.items()
        ],
        "limitations": [
            "B0 is a local model without search tools or trial records in its prompt.",
            "B0 NCT IDs are checked against the live ClinicalTrials.gov API; temporary API failures abort evaluation.",
            "B1 and Final IDs come from NCT-validated records in the historical TREC snapshot.",
            "P@10 and nDCG@10 are computed on the selected qrels-judged closed corpus.",
            "This synthetic/benchmark experiment is not clinical validation.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare a tool-less local LLM with TREC B1 and Final runs."
    )
    parser.add_argument("--topics", required=True, nargs="+", type=Path)
    parser.add_argument("--model", required=True, help="Installed local Ollama model.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/trec_b0_comparison.json",
    )
    args = parser.parse_args()
    topic_data = load_topic_files(args.topics)
    if len(topic_data["query_ids"]) < 25:
        parser.error("The TREC evaluation requires at least 25 selected topics.")
    result = run_b0_evaluation(topic_data, args.model, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
