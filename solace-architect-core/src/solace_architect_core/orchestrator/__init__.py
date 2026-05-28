"""Deterministic Design-phase orchestration.

This package holds the server-side "brain" for the rebuilt Design engine: a
single-writer state model and a pure decision function that decides what runs
next. Control flow lives here as ordinary, unit-testable Python — NOT inside an
LLM prompt and NOT spread across a frontend loop + scattered status files. That
is the architectural fix for the class of bugs the classic Design path hit
(two writers clobbering shared state, completed scopes re-executing, an
elaborate resume machinery to recover from mid-stream agent deaths).
"""

from __future__ import annotations
