from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import httpx

try:
    import ir_datasets
except ImportError as error:
    raise SystemExit("Install evaluation dependencies with: pip install -e '.[evaluation]'") from error


ROOT = Path(__file__).resolve().parents[1]
SELECTION = json.loads((ROOT / "data/trec_qids.json").read_text(encoding="utf-8"))
OUTPUT = ROOT / "data/eval"
QRELS_2022_URL = "https://trec.nist.gov/data/trials/qrels2022.txt"
MINIMUM_FREE_SPACE = 1024**3
_NCT_ID = re.compile(r"NCT\d{8}", re.IGNORECASE)


def parse_qrels_lines(lines: list[str], query_ids: set[str]) -> list[dict[str, Any]]:
    qrels = []
    for line in lines:
        columns = line.split()
        if not columns or columns[0] not in query_ids:
            continue
        if len(columns) != 4:
            raise ValueError(f"Malformed TREC qrels row: {line!r}")
        qrels.append(
            {
                "query_id": columns[0],
                "doc_id": columns[2],
                "relevance": int(columns[3]),
            }
        )
    return qrels


def _document_text(xml_content: bytes) -> tuple[str, str]:
    root = ET.fromstring(xml_content)
    nct_node = root.find(".//nct_id")
    if nct_node is None or not nct_node.text:
        raise ValueError("TREC trial document is missing its NCT identifier.")
    parts = []
    for label, path in (
        ("Title", ".//official_title"),
        ("Brief title", ".//brief_title"),
        ("Condition", ".//condition"),
        ("Summary", ".//brief_summary"),
        ("Description", ".//detailed_description"),
        ("Eligibility", ".//eligibility/criteria"),
    ):
        node = root.find(path)
        if node is not None:
            text = " ".join("".join(node.itertext()).split())
            if text:
                parts.append(f"{label}: {text}")
    return nct_node.text.strip(), "\n".join(parts)


def _download_documents(dataset: Any, requested_ids: set[str]) -> dict[str, str]:
    documents: dict[str, str] = {}
    downloads = dataset.docs_handler()._dlcs
    missing_bytes = sum(
        int(item._size_hint or 0)
        for item in downloads
        if not Path(item.path(force=False)).exists()
    )
    free_bytes = shutil.disk_usage(ROOT).free
    if missing_bytes + MINIMUM_FREE_SPACE > free_bytes:
        raise RuntimeError(
            "Not enough free disk space for the TREC snapshot. "
            f"Need at least {(missing_bytes + MINIMUM_FREE_SPACE) / 1024**3:.2f} GiB "
            f"including a 1 GiB safety reserve; "
            f"{free_bytes / 1024**3:.2f} GiB is available."
        )

    for download in downloads:
        archive_path = Path(download.path())
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if not entry.filename.casefold().endswith(".xml"):
                    continue
                filename_id = _NCT_ID.search(Path(entry.filename).name)
                if filename_id and filename_id.group().upper() not in requested_ids:
                    continue
                with archive.open(entry) as source:
                    nct_id, text = _document_text(source.read())
                if nct_id in requested_ids:
                    documents[nct_id] = text
        if documents.keys() >= requested_ids:
            break

    missing = requested_ids - documents.keys()
    if missing:
        raise RuntimeError(
            f"{len(missing)} qrels-referenced trials were absent from the TREC snapshot: "
            f"{sorted(missing)[:10]}"
        )
    return documents


def _get_qrels(
    dataset_name: str,
    query_ids: set[str],
    dataset: Any,
) -> list[dict[str, Any]]:
    if dataset_name.endswith("trec-ct-2022"):
        response = httpx.get(QRELS_2022_URL, timeout=30)
        response.raise_for_status()
        return parse_qrels_lines(response.text.splitlines(), query_ids)

    return [
        {
            "query_id": item.query_id,
            "doc_id": item.doc_id,
            "relevance": int(item.relevance),
        }
        for item in dataset.qrels_iter()
        if item.query_id in query_ids
    ]


def main() -> None:
    grouped: dict[str, set[str]] = {}
    for selected in SELECTION["topics"]:
        grouped.setdefault(selected["dataset"], set()).add(selected["query_id"])

    selected_data = []
    all_document_ids: set[str] = set()
    for dataset_name, query_ids in grouped.items():
        dataset = ir_datasets.load(dataset_name)
        queries = {
            query.query_id: query.text
            for query in dataset.queries_iter()
            if query.query_id in query_ids
        }
        missing_queries = query_ids - queries.keys()
        if missing_queries:
            raise RuntimeError(
                f"{dataset_name} is missing selected topic IDs: {sorted(missing_queries)}"
            )

        qrels = _get_qrels(dataset_name, query_ids, dataset)
        missing_qrels = query_ids - {item["query_id"] for item in qrels}
        if missing_qrels:
            raise RuntimeError(
                f"{dataset_name} has no judgments for selected topics: "
                f"{sorted(missing_qrels)}"
            )
        all_document_ids.update(item["doc_id"] for item in qrels)
        selected_data.append((dataset_name, queries, qrels))

    corpus = ir_datasets.load("clinicaltrials/2021")
    documents = _download_documents(corpus, all_document_ids)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    for dataset_name, queries, qrels in selected_data:
        year = "2021" if dataset_name.endswith("2021") else "2022"
        destination = OUTPUT / f"trec_{year}.json"
        selected_doc_ids = {item["doc_id"] for item in qrels}
        destination.write_text(
            json.dumps(
                {
                    "dataset": dataset_name,
                    "source": (
                        "TREC Clinical Trials; 2021 qrels via ir_datasets, "
                        "2022 qrels via NIST; judged documents from the April 2021 snapshot"
                    ),
                    "query_ids": sorted(queries, key=int),
                    "topics": queries,
                    "qrels": qrels,
                    "documents": {
                        doc_id: documents[doc_id] for doc_id in sorted(selected_doc_ids)
                    },
                    "relevance_labels": {
                        "0": "not relevant",
                        "1": "excluded",
                        "2": "eligible",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            f"{destination.relative_to(ROOT)}: {len(queries)} topics, "
            f"{len(qrels)} judgments, {len(selected_doc_ids)} judged documents"
        )


if __name__ == "__main__":
    main()
