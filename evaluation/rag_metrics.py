from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RagSample:
    question: str
    expected_answer: str
    generated_answer: str
    gold_contexts: list[str]
    retrieved_contexts: list[str]


def _tokenize(text: str) -> set[str]:
    punctuation = ".,:;!?()[]{}\"'`"
    return {token.strip(punctuation).lower() for token in text.split() if token.strip()}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def context_precision(sample: RagSample) -> float:
    if not sample.retrieved_contexts:
        return 0.0

    matches = 0
    for retrieved in sample.retrieved_contexts:
        if any(_jaccard(retrieved, gold) >= 0.2 for gold in sample.gold_contexts):
            matches += 1
    return matches / len(sample.retrieved_contexts)


def context_recall(sample: RagSample) -> float:
    if not sample.gold_contexts:
        return 0.0

    matched = 0
    for gold in sample.gold_contexts:
        if any(_jaccard(gold, retrieved) >= 0.2 for retrieved in sample.retrieved_contexts):
            matched += 1
    return matched / len(sample.gold_contexts)


def answer_relevance(sample: RagSample) -> float:
    return _jaccard(sample.generated_answer, sample.expected_answer)
