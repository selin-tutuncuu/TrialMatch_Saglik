from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trialmatch.criteria import rank_trial_evaluations
from trialmatch.models import TrialSummary
from trialmatch.profile import extract_patient_profile

from trialmatch.evaluation import ndcg_at_10, precision_at_10


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"\w+", normalized)


def expand_query(query: str, lexicon: dict[str, list[str]]) -> str:
    normalized = query.casefold()
    expansions = []
    for turkish, variants in lexicon.items():
        if any(variant.casefold() in normalized for variant in variants):
            expansions.extend(variants)
            expansions.append(turkish)
    return " ".join([query, *dict.fromkeys(expansions)])


def bm25_scores(query: str, documents: dict[str, str]) -> dict[str, float]:
    tokenized = {doc_id: tokenize(text) for doc_id, text in documents.items()}
    if not tokenized:
        return {}
    average_length = sum(map(len, tokenized.values())) / len(tokenized)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized.values():
        document_frequency.update(set(tokens))
    query_terms = Counter(tokenize(query))
    scores = {}
    for doc_id, tokens in tokenized.items():
        frequencies = Counter(tokens)
        score = 0.0
        for term, query_frequency in query_terms.items():
            frequency = frequencies[term]
            if not frequency:
                continue
            inverse_frequency = math.log(
                1
                + (len(tokenized) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(tokens) / max(average_length, 1)
            )
            score += (
                inverse_frequency
                * frequency
                * 2.5
                / denominator
                * min(query_frequency, 3)
            )
        scores[doc_id] = score
    return scores


def ranked_ids(scores: dict[str, float]) -> list[str]:
    return [
        doc_id
        for doc_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    ]


def _document_field(document: str, field: str) -> str:
    match = re.search(
        rf"(?:^|\n){re.escape(field)}:\s*(.*?)(?=\n[A-Za-z][A-Za-z ]*:\s*|\Z)",
        document,
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _criterion_rerank(query: str, candidate_ids: list[str], documents: dict[str, str]) -> list[str]:
    profile = extract_patient_profile(query)
    trials = [
        TrialSummary(
            nct_id=doc_id,
            title=_document_field(documents[doc_id], "Title") or doc_id,
            status="RECRUITING",
            conditions=[_document_field(documents[doc_id], "Condition")],
            eligibility_criteria=_document_field(documents[doc_id], "Eligibility") or None,
            source_url=f"https://clinicaltrials.gov/study/{doc_id}",
            fetched_at="2021-04-27T00:00:00Z",
        )
        for doc_id in candidate_ids
        if doc_id in documents
    ]
    return [
        result[0].nct_id
        for result in rank_trial_evaluations(trials, profile)
    ]


def run_evaluation(
    topic_data: dict[str, Any],
    lexicon: dict[str, list[str]],
    enable_embeddings: bool = False,
) -> dict[str, Any]:
    qrels: dict[str, dict[str, int]] = {}
    for item in topic_data["qrels"]:
        qrels.setdefault(item["query_id"], {})[item["doc_id"]] = int(item["relevance"])

    baseline_run = {}
    hybrid_run = {}
    embedding_run = {}
    final_run = {}
    rows = []
    model = None
    if enable_embeddings:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Embedding evaluation requires requirements-semantic.txt."
            ) from error
        model = SentenceTransformer("intfloat/multilingual-e5-small")
    for query_id in topic_data["query_ids"]:
        topic = topic_data["topics"][query_id]
        judgments = qrels.get(query_id, {})
        documents = {
            doc_id: topic_data["documents"][doc_id]
            for doc_id in judgments
            if doc_id in topic_data["documents"]
        }
        baseline = ranked_ids(bm25_scores(topic, documents))
        expanded_scores = bm25_scores(expand_query(topic, lexicon), documents)
        expanded = ranked_ids(expanded_scores)
        final_ranked = _criterion_rerank(topic, baseline[:100], documents)
        baseline_run[query_id] = baseline[:100]
        hybrid_run[query_id] = expanded[:100]
        final_run[query_id] = final_ranked[:100]
        row = {
                "query_id": query_id,
                "B1_P@10": precision_at_10(baseline, judgments),
                "B1_nDCG@10": ndcg_at_10(baseline, judgments),
                "hybrid_P@10": precision_at_10(expanded, judgments),
                "hybrid_nDCG@10": ndcg_at_10(expanded, judgments),
                "Final_P@10": precision_at_10(final_ranked, judgments),
                "Final_nDCG@10": ndcg_at_10(final_ranked, judgments),
            }
        if model is not None and documents:
            document_ids = list(documents)
            vectors = model.encode(
                [f"passage: {documents[doc_id]}" for doc_id in document_ids],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            query_vector = model.encode(
                [f"query: {topic}"],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]
            dense_scores = {
                doc_id: float(query_vector @ vector)
                for doc_id, vector in zip(document_ids, vectors)
            }
            min_dense = min(dense_scores.values())
            max_dense = max(dense_scores.values())
            normalized_dense = {
                doc_id: (
                    (score - min_dense) / (max_dense - min_dense)
                    if max_dense > min_dense else 0.0
                )
                for doc_id, score in dense_scores.items()
            }
            max_lexical = max(expanded_scores.values(), default=0.0)
            normalized_lexical = {
                doc_id: score / max_lexical if max_lexical > 0 else 0.0
                for doc_id, score in expanded_scores.items()
            }
            combined = {
                doc_id: 0.4 * normalized_dense[doc_id] + 0.6 * normalized_lexical[doc_id]
                for doc_id in documents
            }
            final_ranked = ranked_ids(combined)
            embedding_run[query_id] = final_ranked[:100]
            row["e5_hybrid_P@10"] = precision_at_10(final_ranked, judgments)
            row["e5_hybrid_nDCG@10"] = ndcg_at_10(final_ranked, judgments)
        rows.append(row)
    count = len(rows)
    result = {
        "dataset": topic_data["dataset"],
        "topics": count,
        "candidate_scope": "qrels-judged documents bundled for each selected topic",
        "B1": {
            "description": "BM25 keyword retrieval without terminology expansion",
            "macro_P@10": sum(row["B1_P@10"] for row in rows) / count if count else 0,
            "macro_nDCG@10": sum(row["B1_nDCG@10"] for row in rows) / count if count else 0,
            "run": baseline_run,
        },
        "terminology_expanded": {
            "description": "BM25 retrieval with the project's curated TR/EN terminology bridge",
            "macro_P@10": sum(row["hybrid_P@10"] for row in rows) / count if count else 0,
            "macro_nDCG@10": sum(row["hybrid_nDCG@10"] for row in rows) / count if count else 0,
            "run": hybrid_run,
        },
        "Final": {
            "description": (
                "B1's top-100 judged-document candidates reranked by the project's "
                "criterion evaluator; selected TREC topics only."
            ),
            "macro_P@10": sum(row["Final_P@10"] for row in rows) / count if count else 0,
            "macro_nDCG@10": sum(row["Final_nDCG@10"] for row in rows) / count if count else 0,
            "run": final_run,
        },
        "per_topic": rows,
        "note": (
            "This is a closed-corpus retrieval ablation, not an end-to-end "
            "clinical eligibility or live API evaluation. Unjudged records are not included."
        ),
    }
    if model is not None:
        result["e5_hybrid"] = {
            "description": (
                "BM25 terminology expansion combined with multilingual-e5-small cosine "
                "similarity; same model prefixes for query and passage."
            ),
            "macro_P@10": sum(row["e5_hybrid_P@10"] for row in rows) / count if count else 0,
            "macro_nDCG@10": sum(row["e5_hybrid_nDCG@10"] for row in rows) / count if count else 0,
            "run": embedding_run,
        }
    return result


def load_topic_files(paths: list[Path]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "dataset": "TREC Clinical Trials 2021+2022",
        "query_ids": [],
        "topics": {},
        "qrels": [],
        "documents": {},
    }
    for path in paths:
        dataset = json.loads(path.read_text(encoding="utf-8"))
        year = path.stem.rsplit("_", 1)[-1]
        for query_id in dataset["query_ids"]:
            merged_id = f"{year}:{query_id}"
            merged["query_ids"].append(merged_id)
            merged["topics"][merged_id] = dataset["topics"][query_id]
        merged["qrels"].extend(
            {**item, "query_id": f"{year}:{item['query_id']}"}
            for item in dataset["qrels"]
        )
        merged["documents"].update(dataset["documents"])
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run reproducible keyword and TR/EN hybrid TREC retrieval baselines."
    )
    parser.add_argument("--topics", required=True, nargs="+", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/trec_baseline_comparison.json",
    )
    parser.add_argument(
        "--enable-embeddings",
        action="store_true",
        help="Optional; downloads/loads multilingual-e5-small for the dense ablation.",
    )
    args = parser.parse_args()
    topic_data = load_topic_files(args.topics)
    lexicon = json.loads((ROOT / "data/term_lexicon.json").read_text(encoding="utf-8"))
    if len(topic_data.get("query_ids", [])) < 25:
        parser.error("The TREC evaluation requires at least 25 selected topics.")
    result = run_evaluation(topic_data, lexicon, enable_embeddings=args.enable_embeddings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
