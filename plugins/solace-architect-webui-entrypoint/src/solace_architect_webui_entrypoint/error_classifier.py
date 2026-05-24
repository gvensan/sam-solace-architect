"""Classify SAM-formatted error messages into stable category codes.

SAM's ``common/error_handlers.py`` maps LiteLLM exception types to a small
set of user-friendly message strings (CONTEXT_LIMIT_ERROR_MESSAGE,
RATE_LIMIT_ERROR_MESSAGE, etc.). Those strings flow through to the
gateway as the ``JSONRPCError.message`` payload. By the time they reach
our gateway, we've lost the exception class.

This module re-derives a structured category code by pattern-matching
SAM's stable message prefixes. The category is attached to the SSE Error
event so the frontend can switch on a stable identifier rather than a
substring of the user-facing string (which is fragile when SAM rewords
messages).

Keep this list in sync with
``solace_agent_mesh/common/error_handlers.py`` — the message constants
there are the source of truth. We anchor on stable opening phrases that
SAM is unlikely to change.
"""

from __future__ import annotations

from typing import Tuple

# (category_code, anchor_phrase) pairs. First match wins; check more-specific
# patterns first so e.g. "service is temporarily unavailable" doesn't fall
# through to a generic "service" matcher.
_PATTERNS: list[Tuple[str, str]] = [
    ("context_limit",      "conversation history has become too long"),
    ("rate_limit",         "rate limit has been exceeded"),
    ("service_unavailable","llm service is temporarily unavailable"),
    ("authentication",     "rejected the authentication credentials"),
    ("api_connection",     "unable to connect to the llm service"),
    ("timeout",            "request to the llm service timed out"),
    ("content_policy",     "blocked by content safety filters"),
    ("not_found",          "configured llm model was not found"),
    ("permission_denied",  "access to the llm model was denied"),
    ("internal_server",    "llm service encountered an internal error"),
    ("budget_exceeded",    "llm usage budget has been exceeded"),
    ("bad_request",        "llm service rejected the request"),
    # Stream-drop family — these are the raw underlying errors we sometimes
    # see in our SSE Error events before SAM's friendly-string rewrite kicks
    # in (e.g. cross-agent failures, ADK runner internal errors).
    ("stream_drop",        "midstreamfallbackerror"),
    ("stream_drop",        "incomplete chunked read"),
    ("stream_drop",        "peer closed connection"),
    ("max_output_limit",   "last event shouldn't be partial"),
    ("max_output_limit",   "llm max output limit"),
    # API-layer transient errors — observed 2026-05-24: LLM proxy returned
    # an HTML error body instead of JSON (provider hard-down). These leak
    # through SAM as raw exception classes (litellm.APIError /
    # OpenAIException) — match the raw forms so auto-resume + escalation
    # treat them as transient instead of falling into "unexpected".
    ("service_unavailable","openaiexception - <html>"),
    ("service_unavailable","apiconnectionerror"),
    ("service_unavailable","litellm.apierror"),
    ("service_unavailable","litellm.apiconnectionerror"),
    # SAM's catch-all for unknown LLM failures
    ("llm_default",        "error occurred while communicating with the llm service"),
    # Generic frontend-visible message that SAM's gateway emits when it
    # doesn't have a more specific classification.
    ("unexpected",         "an unexpected error occurred"),
]

# Category → severity. Used by the frontend to decide whether to auto-retry,
# offer a fresh session, or just report the error.
_SEVERITY: dict[str, str] = {
    "context_limit":       "session_full",    # only a fresh session fixes it
    "rate_limit":          "transient",       # back off and retry
    "service_unavailable": "transient",
    "authentication":      "config",          # operator action needed
    "api_connection":      "config",
    "timeout":             "transient",
    "content_policy":      "user_action",     # rephrase
    "not_found":           "config",
    "permission_denied":   "config",
    "internal_server":     "transient",
    "budget_exceeded":     "config",
    "bad_request":         "user_action",
    "stream_drop":         "transient",
    "max_output_limit":    "transient",
    "llm_default":         "transient",
    "unexpected":          "unknown",
}


def classify(message: str) -> dict:
    """Classify a SAM-formatted error message.

    Returns a dict with:
      - ``category``: one of the codes above (or ``"unknown"`` if no match)
      - ``severity``: one of ``transient`` / ``session_full`` / ``config``
        / ``user_action`` / ``unknown``
      - ``auto_retryable``: True for transient categories where a simple
        re-dispatch (or auto-resume) is the right action; False otherwise

    Pattern-matching is case-insensitive against the lowercased message.
    """
    haystack = (message or "").lower()
    for code, phrase in _PATTERNS:
        if phrase in haystack:
            severity = _SEVERITY.get(code, "unknown")
            return {
                "category": code,
                "severity": severity,
                "auto_retryable": severity == "transient",
            }
    return {"category": "unknown", "severity": "unknown", "auto_retryable": False}
