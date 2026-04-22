"""Rule loader + safe expression evaluator.

Rule expressions are a tiny allowlisted subset of Python evaluated via the `ast`
module — no builtins, no function calls, no attribute access. This avoids a
third-party dep (asteval) while keeping the YAML-style ergonomics from the
design doc. Config uses JSON so we don't need PyYAML either.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare,
    ast.And, ast.Or, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Name, ast.Load, ast.Constant,
    ast.List, ast.Tuple, ast.Set,
)


class RuleError(ValueError):
    """Raised when a rule fails to parse or evaluate."""


@dataclass(frozen=True)
class Rule:
    id: str
    expression: ast.Expression
    reason: str


@dataclass(frozen=True)
class RuleSet:
    version: int
    rules: tuple[Rule, ...]
    baseline_invoke_rate: float


def _compile(expr: str) -> ast.Expression:
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise RuleError(f"disallowed syntax in rule: {type(node).__name__}")
    return tree


def evaluate(expr: ast.Expression, event: dict[str, Any]) -> bool:
    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return event.get(node.id)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [_eval(e) for e in node.elts]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not _eval(node.operand)
        if isinstance(node, ast.BoolOp):
            values = [_eval(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                if not _apply_cmp(op, left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BinOp):
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
        raise RuleError(f"cannot evaluate node: {type(node).__name__}")

    result = _eval(expr)
    if result is None:
        return False
    return bool(result)


def _apply_cmp(op: ast.cmpop, left: Any, right: Any) -> bool:
    if left is None or right is None:
        if isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            pass  # None comparisons are allowed for equality / membership
        else:
            return False
    if isinstance(op, ast.Eq): return left == right
    if isinstance(op, ast.NotEq): return left != right
    if isinstance(op, ast.Lt): return left < right
    if isinstance(op, ast.LtE): return left <= right
    if isinstance(op, ast.Gt): return left > right
    if isinstance(op, ast.GtE): return left >= right
    if isinstance(op, ast.In): return left in (right or [])
    if isinstance(op, ast.NotIn): return left not in (right or [])
    raise RuleError(f"unsupported comparison: {type(op).__name__}")


def load(path: str | Path) -> RuleSet:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = tuple(
        Rule(id=r["id"], expression=_compile(r["when"]), reason=r.get("reason", r["id"]))
        for r in data.get("rules", [])
    )
    sampling = data.get("sampling", {}) or {}
    return RuleSet(
        version=int(data.get("version", 1)),
        rules=rules,
        baseline_invoke_rate=float(sampling.get("baseline_invoke_rate", 0.0)),
    )


def matched_rules(event: dict[str, Any], ruleset: RuleSet) -> list[Rule]:
    return [r for r in ruleset.rules if evaluate(r.expression, event)]
