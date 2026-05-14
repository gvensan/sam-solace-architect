"""Skill-routing operator evaluator (v2spec §5.1).

Evaluates the per-step ``when`` clauses in ``configs/skill-routing.yaml`` against a
discovery brief. Supports operators: equals, in, not_in, contains_any, contains_all,
not_empty, empty, matches, gt, lt, gte, lte. AND across clauses; ``any_of`` block for OR.

Field paths use dot notation with ``[*]`` to project across arrays (JSONPath-lite).
"""

from __future__ import annotations

import re
from typing import Any


def _resolve_field(brief: Any, path: str) -> list:
    """Resolve a dotted path with [*] array projection. Returns a list of values."""
    parts = path.split(".")
    current = [brief]
    for part in parts:
        if part.endswith("[*]"):
            key = part[:-3]
            new_current = []
            for c in current:
                if isinstance(c, dict):
                    v = c.get(key)
                    if isinstance(v, list):
                        new_current.extend(v)
                    elif v is not None:
                        new_current.append(v)
            current = new_current
        else:
            new_current = []
            for c in current:
                if isinstance(c, dict) and part in c:
                    new_current.append(c[part])
                elif isinstance(c, list):
                    # auto-project across the list
                    for item in c:
                        if isinstance(item, dict) and part in item:
                            new_current.append(item[part])
            current = new_current
    return current


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, (str, list, dict)) and len(v) == 0:
        return True
    return False


def _eval_clause(brief: Any, clause: dict) -> bool:
    field = clause["field"]
    op = clause["op"]
    expected = clause.get("value")

    values = _resolve_field(brief, field)
    # For not_empty / empty, evaluate against the resolved list itself.
    if op == "not_empty":
        return any(not _is_empty(v) for v in values)
    if op == "empty":
        return all(_is_empty(v) for v in values) if values else True
    if not values:
        # If field doesn't resolve to anything, only `empty` succeeds (above).
        return False

    if op == "equals":
        return any(v == expected for v in values)
    if op == "in":
        return any(v in expected for v in values)
    if op == "not_in":
        return all(v not in expected for v in values)
    if op == "contains_any":
        # values may be lists or strings; expected is a list
        for v in values:
            if isinstance(v, list):
                if any(e in v for e in expected):
                    return True
            elif isinstance(v, str):
                lower = v.lower()
                if any(e.lower() in lower for e in expected):
                    return True
        return False
    if op == "contains_all":
        for v in values:
            if isinstance(v, list):
                if all(e in v for e in expected):
                    return True
            elif isinstance(v, str):
                lower = v.lower()
                if all(e.lower() in lower for e in expected):
                    return True
        return False
    if op == "matches":
        return any(isinstance(v, str) and re.search(expected, v) for v in values)
    if op in ("gt", "lt", "gte", "lte"):
        cmps = {"gt": lambda a, b: a > b, "lt": lambda a, b: a < b,
                "gte": lambda a, b: a >= b, "lte": lambda a, b: a <= b}[op]
        try:
            return any(cmps(v, expected) for v in values)
        except TypeError:
            return False
    raise ValueError(f"unknown operator: {op!r}")


def evaluate_when(brief: Any, when: list | dict | None) -> bool:
    """Evaluate a ``when`` block. Returns True if the step is included.

    - list of clauses → AND across them
    - dict with ``any_of: [clauses]`` → OR
    - missing/empty → True (unconditional)
    """
    if not when:
        return True
    if isinstance(when, dict) and "any_of" in when:
        return any(_eval_clause(brief, c) for c in when["any_of"])
    return all(_eval_clause(brief, c) for c in when)
