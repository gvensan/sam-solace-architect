"""Defensive type coercion for tool arguments.

LiteLLM and ADK occasionally hand structured tool args (lists, dicts) to a tool
function as a **JSON-encoded string** instead of the native Python type the
tool declares. The classic symptom — first found in ``record_scope_progress`` —
is calling ``list(scopes_done)`` on what looks like a list but is actually a
string, which yields one entry per character:

    list('["topic-design","broker-select"]')
    # → ['[', '"', 't', 'o', 'p', 'i', 'c', '-', 'd', ...]

The corrupted value then propagates downstream (storage, replay, UI) and
surfaces as visibly broken output much later. By the time anyone notices,
the linked engagement may have several scopes' worth of corrupted state.

The fix is uniform: every tool that takes a list/dict arg should normalize
it at entry. Rather than duplicate the same five-line block in every tool,
we expose a single ``@coerce_args`` decorator that inspects the wrapped
function's signature and, for each parameter whose annotation says
``list``/``List[...]``/``Optional[list]`` (or the dict equivalents),
JSON-decodes string-valued arguments back to the native type.

Behaviour rules
---------------
- Strings that parse to the declared container type → coerced silently.
- Strings that parse but to the *wrong* container type → wrapped in a single-
  element list (for list params) or rejected with a TypeError (for dicts).
- Strings that don't parse as JSON → wrapped in a single-element list (for
  list params, the typical case of "you meant one item"). Rejected for dicts.
- Already-correct native types → passed through untouched (zero overhead).
- ``None`` / missing → passed through untouched.

The decorator is type-hint driven, so adopting it is free: just add the
decorator above the tool. No call-site changes needed.
"""

from __future__ import annotations

import functools
import inspect
import json
import typing as _t


def _is_list_annotation(ann: _t.Any) -> bool:
    """True if the annotation is ``list``, ``List[...]``, ``Optional[list]``,
    or similar — i.e. the declared type accepts a list at runtime."""
    if ann is list or ann is _t.List:
        return True
    origin = _t.get_origin(ann)
    if origin in (list, _t.List):
        return True
    # Optional[X] / Union[X, None] — recurse into the args.
    if origin is _t.Union:
        return any(_is_list_annotation(a) for a in _t.get_args(ann))
    return False


def _is_dict_annotation(ann: _t.Any) -> bool:
    """True if the annotation accepts a dict at runtime."""
    if ann is dict or ann is _t.Dict:
        return True
    origin = _t.get_origin(ann)
    if origin in (dict, _t.Dict):
        return True
    if origin is _t.Union:
        return any(_is_dict_annotation(a) for a in _t.get_args(ann))
    return False


def _coerce_one(value: _t.Any, expects_list: bool, expects_dict: bool) -> _t.Any:
    """Coerce a single argument. Pass-through unless it's a string that
    needs JSON-parsing back to the declared container type."""
    if not isinstance(value, str):
        return value
    if not (expects_list or expects_dict):
        return value
    # Try JSON-parsing; on failure, fall back to a single-element list for
    # list-typed args, or raise for dict-typed (a malformed JSON object is
    # almost never what the caller intended).
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        if expects_list:
            return [value] if value.strip() else []
        raise TypeError(
            f"expected dict, got non-JSON string {value!r}"
        )
    if expects_list:
        if isinstance(parsed, list):
            return parsed
        # User meant one item — wrap it.
        return [parsed]
    if expects_dict:
        if isinstance(parsed, dict):
            return parsed
        raise TypeError(
            f"expected dict, got JSON value of type {type(parsed).__name__}: {parsed!r}"
        )
    return value


def coerce_args(fn):
    """Decorator that JSON-decodes list/dict args delivered as strings.

    Inspects the wrapped function's signature; for every parameter whose
    annotation accepts a list (or dict), any caller-supplied string is
    JSON-parsed and substituted. Non-string values and non-list/dict-typed
    parameters are passed through unmodified.

    Works for both ``async def`` and plain ``def`` tools. Preserves the
    function's identity / name / docstring (``functools.wraps``) so SAM's
    tool-discovery machinery still sees the original signature.

    Example::

        @coerce_args
        async def record_scope_progress(
            engagement_id: str,
            scopes_done: Optional[list] = None,
            ...
        ) -> ToolResult:
            # `scopes_done` is guaranteed to be a list (or None) here,
            # even if LiteLLM passed it as '["topic-design","broker-select"]'.
            ...
    """
    sig = inspect.signature(fn)
    # Pre-compute which params need coercion so the per-call overhead is
    # just one dict lookup per arg.
    list_params: set[str] = set()
    dict_params: set[str] = set()
    for name, param in sig.parameters.items():
        if param.annotation is inspect.Parameter.empty:
            continue
        if _is_list_annotation(param.annotation):
            list_params.add(name)
        if _is_dict_annotation(param.annotation):
            dict_params.add(name)
    if not list_params and not dict_params:
        return fn    # nothing to do; return the original function unwrapped

    def _normalise(args, kwargs):
        try:
            bound = sig.bind_partial(*args, **kwargs)
        except TypeError:
            # Caller passed mismatched args; let the function itself raise
            # the meaningful error rather than mask it here.
            return args, kwargs
        for name, value in list(bound.arguments.items()):
            expects_list = name in list_params
            expects_dict = name in dict_params
            if expects_list or expects_dict:
                bound.arguments[name] = _coerce_one(value, expects_list, expects_dict)
        # Re-extract args/kwargs from the bound signature in their canonical shape.
        return bound.args, bound.kwargs

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _async_wrapper(*args, **kwargs):
            args, kwargs = _normalise(args, kwargs)
            return await fn(*args, **kwargs)
        return _async_wrapper

    @functools.wraps(fn)
    def _sync_wrapper(*args, **kwargs):
        args, kwargs = _normalise(args, kwargs)
        return fn(*args, **kwargs)
    return _sync_wrapper


__all__ = ["coerce_args"]
