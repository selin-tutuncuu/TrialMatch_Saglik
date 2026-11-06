from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def precision_at_10(ranked_ids: Sequence[str], qrels: Mapping[str, int]) -> float:
    top = list(ranked_ids[:10])
    return sum(qrels.get(identifier, 0) == 2 for identifier in top) / 10


def ndcg_at_10(ranked_ids: Sequence[str], qrels: Mapping[str, int]) -> float:
    """Use the TREC relevance label (0/1/2) directly as gain."""
    gains = [qrels.get(identifier, 0) for identifier in ranked_ids[:10]]
    dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sorted(qrels.values(), reverse=True)[:10]
    idcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def hallucination_rate(recommended_ids: Sequence[str], verified_ids: set[str]) -> float:
    if not recommended_ids:
        return 0.0
    return sum(identifier not in verified_ids for identifier in recommended_ids) / len(recommended_ids)


def criterion_accuracy(expected: Sequence[str], predicted: Sequence[str]) -> float:
    if not expected or len(expected) != len(predicted):
        raise ValueError("Expected and predicted decisions must have the same non-zero length.")
    return sum(left == right for left, right in zip(expected, predicted)) / len(expected)


def unknown_recall(expected: Sequence[str], predicted: Sequence[str]) -> float:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted decisions must have the same length.")
    unknown_count = sum(item == "UNKNOWN" for item in expected)
    if not unknown_count:
        return 0.0
    return sum(
        expected_item == "UNKNOWN" and predicted_item == "UNKNOWN"
        for expected_item, predicted_item in zip(expected, predicted)
    ) / unknown_count
