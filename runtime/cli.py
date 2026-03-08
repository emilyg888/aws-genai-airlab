from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.orchestrator import AgentOrchestrator
from tools.bedrock_client import BedrockClient
from tools.diagram_tool import write_diagram_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AWS Generative AI AirLab CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tutor = subparsers.add_parser("tutor", help="Explain AWS architecture with RAG context")
    tutor.add_argument("--question", required=True)
    tutor.add_argument("--diagram-out", default="", help="Optional output path for Mermaid diagram")

    quiz = subparsers.add_parser("quiz", help="Generate exam-style questions")
    quiz.add_argument("--topic", required=True)
    quiz.add_argument("--count", type=int, default=5)
    quiz.add_argument("--difficulty", default="associate")

    review = subparsers.add_parser("review", help="Review and score an architecture design")
    review.add_argument("--diagram-file", required=True)
    review.add_argument("--rationale", default="")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    bedrock = BedrockClient()
    orchestrator = AgentOrchestrator(bedrock)

    if args.command == "tutor":
        result = orchestrator.run("tutor", {"question": args.question, "include_diagram": True})
        print(json.dumps(result.output, indent=2, default=str))
        if args.diagram_out:
            diagram = result.output.get("diagram_mermaid")
            if diagram:
                output_path = write_diagram_file(diagram, Path(args.diagram_out))
                print(f"Saved diagram to {output_path}")
        return 0

    if args.command == "quiz":
        result = orchestrator.run(
            "quiz",
            {"topic": args.topic, "count": args.count, "difficulty": args.difficulty},
        )
        print(json.dumps(result.output, indent=2, default=str))
        return 0

    if args.command == "review":
        diagram_content = Path(args.diagram_file).read_text(encoding="utf-8")
        result = orchestrator.run("review", {"diagram": diagram_content, "rationale": args.rationale})
        print(json.dumps(result.output, indent=2, default=str))
        return 0

    raise ValueError("Unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
