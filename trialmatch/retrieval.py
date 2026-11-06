from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from pathlib import Path

from trialmatch.criteria import _clean
from trialmatch.models import Criterion


class CriteriaRetriever:
    """Hybrid lexical/synonym retrieval with optional multilingual E5 vectors."""

    def __init__(
        self,
        lexicon_path: Path | None = None,
        enable_embeddings: bool = False,
        model_name: str = "intfloat/multilingual-e5-small",
        index_path: Path | None = None,
        reranker_name: str | None = None,
    ) -> None:
        path = lexicon_path or Path("data/term_lexicon.json")
        self._terms: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self._model = None
        self._model_name = model_name
        self._index_path = index_path
        self._vector_index: dict[str, dict[str, object]] = {}
        self._reranker = None
        if enable_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise RuntimeError(
                    "Semantic retrieval is enabled but sentence-transformers is not installed. "
                    "Install requirements-semantic.txt."
                ) from error
            self._model = SentenceTransformer(model_name)
            if index_path and index_path.exists():
                stored = json.loads(index_path.read_text(encoding="utf-8"))
                if stored.get("model_name") != model_name:
                    stored = {"model_name": model_name, "entries": {}}
                self._vector_index = stored.get("entries", {})
        if reranker_name:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as error:
                raise RuntimeError(
                    "A reranker is configured but sentence-transformers is not installed."
                ) from error
            self._reranker = CrossEncoder(reranker_name)

    def retrieve(
        self,
        query: str,
        criteria: list[Criterion],
        limit: int = 8,
    ) -> list[Criterion]:
        if not criteria or limit <= 0:
            return []
        query_tokens = self._expand(_clean(query))
        scores: list[tuple[float, int]] = []
        for index, criterion in enumerate(criteria):
            tokens = self._expand(_clean(criterion.text))
            overlap = len(query_tokens & tokens)
            lexical = overlap / max(1, len(query_tokens))
            scores.append((lexical, index))

        if self._model is not None:
            query_vector = self._model.encode(
                [f"query: {query}"], normalize_embeddings=True
            )[0]
            keys = [
                hashlib.sha256(
                    f"{self._model_name}\0{item.text}".encode("utf-8")
                ).hexdigest()
                for item in criteria
            ]
            missing = [
                (key, item)
                for key, item in zip(keys, criteria)
                if key not in self._vector_index
            ]
            if missing:
                vectors = self._model.encode(
                    [f"passage: {item.text}" for _, item in missing],
                    normalize_embeddings=True,
                )
                for (key, item), vector in zip(missing, vectors):
                    self._vector_index[key] = {
                        "text": item.text,
                        "vector": vector.tolist(),
                    }
                self._save_vector_index()
            passage_vectors = [self._vector_index[key]["vector"] for key in keys]
            scores = [
                (lexical + float(query_vector @ passage), index)
                for (lexical, index), passage in zip(scores, passage_vectors)
            ]
        if self._reranker is not None:
            rerank_scores = self._reranker.predict(
                [(query, item.text) for item in criteria]
            )
            scores = [
                (float(rerank_scores[index]), index)
                for index in range(len(criteria))
            ]
        scores.sort(key=lambda item: (-item[0], item[1]))
        selected = scores[:limit]
        if self._reranker is None:
            selected = [item for item in selected if item[0] > 0]
        return [criteria[index] for _, index in selected]

    def _save_vector_index(self) -> None:
        if self._index_path is None:
            return
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._index_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"model_name": self._model_name, "entries": self._vector_index},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(self._index_path)

    def _expand(self, text: str) -> set[str]:
        tokens = {token for token in re.findall(r"\w+", text) if len(token) > 2}
        for turkish, english_terms in self._terms.items():
            variants = {_clean(turkish), *(_clean(term) for term in english_terms)}
            if any(variant and variant in text for variant in variants):
                for variant in variants:
                    tokens.update(token for token in re.findall(r"\w+", variant) if len(token) > 2)
        return tokens


def map_terms(
    term: str,
    direction: str = "tr→en",
    lexicon_path: Path | None = None,
) -> list[str]:
    """Map a known condition term to search-language variants without an LLM."""
    path = lexicon_path or Path("data/term_lexicon.json")
    if not path.exists():
        return []
    lexicon: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    normalized_term = _clean(term).strip()
    normalized_direction = unicodedata.normalize("NFKC", direction).casefold()
    if normalized_direction not in {"tr→en", "tr->en", "tr-en", "en→tr", "en->tr", "en-tr"}:
        raise ValueError("direction must be tr→en or en→tr.")

    forward = normalized_direction.startswith("tr")
    mapped: list[str] = []
    for turkish, english_terms in lexicon.items():
        source = [turkish] if forward else english_terms
        destination = english_terms if forward else [turkish]
        matched = any(
            normalized_term == _clean(value)
            or re.search(rf"(?<!\w){re.escape(_clean(value))}(?!\w)", normalized_term)
            for value in source
        )
        if matched:
            mapped.extend(destination)

    return list(dict.fromkeys(mapped))
