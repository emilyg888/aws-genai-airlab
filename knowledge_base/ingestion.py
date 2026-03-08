from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from knowledge_base.chunking import chunk_text
from knowledge_base.config import AirLabConfig

LOGGER = logging.getLogger(__name__)


class DocumentIngestor:
    """Extracts text from PDF files and writes chunked JSON payloads to S3."""

    def __init__(self, config: AirLabConfig) -> None:
        self._config = config
        self._s3 = boto3.client("s3", region_name=config.aws_region)

    def ingest_directory(self, source_dir: Path, prefix: str) -> int:
        if not source_dir.exists() or not source_dir.is_dir():
            raise ValueError(f"Source directory not found: {source_dir}")

        pdf_files = sorted(source_dir.glob("*.pdf"))
        if not pdf_files:
            LOGGER.warning("No PDF files found in %s", source_dir)
            return 0

        uploaded = 0
        for pdf_file in pdf_files:
            payloads = self._extract_pdf_chunks(pdf_file)
            for idx, payload in enumerate(payloads):
                key = f"{prefix}/{pdf_file.stem}/chunk-{idx:04d}.json"
                self._upload_json(key=key, payload=payload)
                uploaded += 1
        LOGGER.info("Uploaded %s chunks to bucket %s", uploaded, self._config.docs_bucket_name)
        return uploaded

    def _extract_pdf_chunks(self, pdf_path: Path) -> list[dict[str, str | int]]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf is required for ingestion. Install requirements first.") from exc

        reader = PdfReader(str(pdf_path))
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        chunks = chunk_text(full_text)

        return [
            {
                "source": pdf_path.name,
                "chunk_index": i,
                "content": chunk,
            }
            for i, chunk in enumerate(chunks)
        ]

    def _upload_json(self, key: str, payload: dict[str, str | int]) -> None:
        if not self._config.docs_bucket_name:
            raise ValueError("DOCS_BUCKET_NAME is required for ingestion")

        try:
            self._s3.put_object(
                Bucket=self._config.docs_bucket_name,
                Key=key,
                Body=json.dumps(payload).encode("utf-8"),
                ContentType="application/json",
            )
        except (BotoCoreError, ClientError) as exc:
            LOGGER.exception("Failed to upload %s", key)
            raise RuntimeError(f"Failed to upload document chunk {key}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest PDF course files into S3 document bucket.")
    parser.add_argument("--source-dir", default="course-materials", help="Directory containing PDF files")
    parser.add_argument("--prefix", default="slides", help="S3 key prefix for uploaded chunks")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    config = AirLabConfig.from_env()
    ingestor = DocumentIngestor(config)
    count = ingestor.ingest_directory(Path(args.source_dir), args.prefix)
    LOGGER.info("Ingestion complete: %s chunks uploaded", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
