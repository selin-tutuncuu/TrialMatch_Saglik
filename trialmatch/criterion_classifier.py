from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable

from trialmatch.criteria import _clean


class NaiveBayesCriterionClassifier:
    """Tiny multinomial classifier trained only on the project's synthetic labels."""

    def __init__(self) -> None:
        self.class_counts: Counter[str] = Counter()
        self.token_counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.total_tokens: Counter[str] = Counter()
        self.vocabulary: set[str] = set()

    @staticmethod
    def _tokens(summary: str, criterion: str) -> list[str]:
        return re.findall(r"\w+", _clean(f"{summary} {criterion}"))

    def fit(self, examples: Iterable[dict[str, str]]) -> None:
        for example in examples:
            label = example["expected"]
            tokens = self._tokens(example["summary"], example["criterion"])
            self.class_counts[label] += 1
            self.token_counts[label].update(tokens)
            self.total_tokens[label] += len(tokens)
            self.vocabulary.update(tokens)
        if not self.class_counts:
            raise ValueError("At least one labelled example is required.")

    def predict(self, summary: str, criterion: str) -> str:
        if not self.class_counts:
            raise ValueError("The classifier has not been trained.")
        tokens = self._tokens(summary, criterion)
        vocabulary_size = max(1, len(self.vocabulary))
        total_examples = sum(self.class_counts.values())
        scores: dict[str, float] = {}
        for label, count in self.class_counts.items():
            score = math.log(count / total_examples)
            denominator = self.total_tokens[label] + vocabulary_size
            for token in tokens:
                score += math.log(
                    (self.token_counts[label][token] + 1) / denominator
                )
            scores[label] = score
        return max(scores, key=scores.get)
