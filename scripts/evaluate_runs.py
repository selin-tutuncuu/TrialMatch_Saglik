from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trialmatch.evaluation import ndcg_at_10, precision_at_10


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate TREC ranking run JSON against selected qrels.")
    parser.add_argument("--topics", required=True, type=Path, help="Generated data/eval/trec_2021.json or trec_2022.json")
    parser.add_argument("--run", required=True, type=Path, help="JSON object mapping query IDs to ranked document IDs")
    args = parser.parse_args()
    topic_data = json.loads(args.topics.read_text(encoding="utf-8"))
    run = json.loads(args.run.read_text(encoding="utf-8"))
    judgments: dict[str, dict[str, int]] = {}
    for item in topic_data["qrels"]:
        judgments.setdefault(item["query_id"], {})[item["doc_id"]] = int(item["relevance"])

    rows = []
    for query_id in topic_data["query_ids"]:
        ranked = run.get(query_id, [])
        qrels = judgments.get(query_id, {})
        rows.append(
            {
                "query_id": query_id,
                "P@10": precision_at_10(ranked, qrels),
                "nDCG@10": ndcg_at_10(ranked, qrels),
            }
        )
    count = len(rows)
    result = {
        "dataset": topic_data["dataset"],
        "topics": count,
        "macro_P@10": sum(row["P@10"] for row in rows) / count if count else 0,
        "macro_nDCG@10": sum(row["nDCG@10"] for row in rows) / count if count else 0,
        "per_topic": rows,
        "gain_definition": "TREC qrels relevance label used directly as gain: 0, 1, 2.",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
