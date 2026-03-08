from __future__ import annotations

from typing import Iterable


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    cleaned = normalize_whitespace(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = end - overlap
    return chunks


def enumerate_chunks(chunks: Iterable[str]) -> list[dict[str, str | int]]:
    return [{"chunk_id": idx, "content": chunk} for idx, chunk in enumerate(chunks)]
