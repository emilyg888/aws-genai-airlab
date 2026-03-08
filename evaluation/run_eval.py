from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.rag_metrics import RagSample, answer_relevance, context_precision, context_recall


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAG evaluation over JSONL samples")
    parser.add_argument("--dataset", required=True, help="Path to JSONL evaluation dataset")
    return parser.parse_args()


def load_samples(path: Path) -> list[RagSample]:
    samples: list[RagSample] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            row = json.loads(line)
            samples.append(
                RagSample(
                    question=row["question"],
                    expected_answer=row["expected_answer"],
                    generated_answer=row["generated_answer"],
                    gold_contexts=row.get("gold_contexts", []),
                    retrieved_contexts=row.get("retrieved_contexts", []),
                )
            )
    return samples


def main() -> int:
    args = parse_args()
    samples = load_samples(Path(args.dataset))

    if not samples:
        print(json.dumps({"count": 0, "error": "No samples loaded"}))
        return 1

    p = sum(context_precision(s) for s in samples) / len(samples)
    r = sum(context_recall(s) for s in samples) / len(samples)
    a = sum(answer_relevance(s) for s in samples) / len(samples)

    print(
        json.dumps(
            {
                "count": len(samples),
                "avg_context_precision": round(p, 4),
                "avg_context_recall": round(r, 4),
                "avg_answer_relevance": round(a, 4),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
