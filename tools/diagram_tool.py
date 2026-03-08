from __future__ import annotations

from pathlib import Path


def ensure_mermaid_diagram(text: str) -> str:
    """Return a Mermaid diagram block.

    If the model output already includes Mermaid markup, pass it through.
    Otherwise, synthesize a starter AWS GenAI flow diagram.
    """
    lowered = text.lower()
    if "```mermaid" in lowered:
        return text

    return """```mermaid
flowchart TD
    user[User/API Client] --> apigw[API Gateway]
    apigw --> tutor[Architecture Tutor Lambda]
    apigw --> quiz[Quiz Generator Lambda]
    apigw --> reviewer[Architecture Reviewer Lambda]
    tutor --> kb[Bedrock Knowledge Base]
    quiz --> kb
    reviewer --> kb
    kb --> vectors[S3 Vectors]
    tutor --> bedrock[Amazon Bedrock Model]
    quiz --> bedrock
    reviewer --> bedrock
```"""


def write_diagram_file(content: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path
