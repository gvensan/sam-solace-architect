"""Smoke tests for the SSE Error-event classifier.

The classifier pattern-matches SAM's stable user-facing message strings
(see ``solace_agent_mesh/common/error_handlers.py``) into category +
severity + auto_retryable. Drift in SAM's wording would silently break
this — these tests anchor on the prefixes we depend on so a refresh
catches the regression at CI time rather than at the user's screen.
"""

import pytest

from solace_architect_webui_entrypoint.error_classifier import classify


def test_context_limit_is_session_full_and_not_retryable():
    """Matches SAM's CONTEXT_LIMIT_ERROR_MESSAGE prefix."""
    r = classify(
        "The conversation history has become too long for the AI model to process. "
        "This can happen after extended conversations. To continue, please start a new conversation."
    )
    assert r["category"] == "context_limit"
    assert r["severity"] == "session_full"
    assert r["auto_retryable"] is False


def test_rate_limit_is_transient_and_retryable():
    r = classify(
        "The LLM service rate limit has been exceeded. Wait a moment and try again."
    )
    assert r["category"] == "rate_limit"
    assert r["severity"] == "transient"
    assert r["auto_retryable"] is True


def test_service_unavailable_is_transient_and_retryable():
    r = classify("The LLM service is temporarily unavailable. Try again in a few minutes.")
    assert r["category"] == "service_unavailable"
    assert r["auto_retryable"] is True


def test_authentication_is_config_not_retryable():
    r = classify(
        "The LLM service rejected the authentication credentials. "
        "Contact an administrator to verify the API key."
    )
    assert r["category"] == "authentication"
    assert r["severity"] == "config"
    assert r["auto_retryable"] is False


def test_stream_drop_raw_pattern():
    """Raw underlying MidStream errors that haven't been rewritten yet."""
    r = classify(
        "litellm.MidStreamFallbackError: peer closed connection without sending "
        "complete message body (incomplete chunked read)"
    )
    assert r["category"] == "stream_drop"
    assert r["auto_retryable"] is True


def test_403_forbidden_is_permission_denied_not_retryable():
    """A 403 from the LLM proxy is an auth / permission issue, NOT a
    transient outage — operator must check the API key. Auto-retrying
    burns budget against a proxy that's reliably saying no.
    Observed 2026-05-24: 270 '403 Forbidden' lines in sam.log produced
    by 30 distinct tasks that the FE auto-resumed against.

    The pattern MUST win over the generic 'openaiexception - <html>'
    pattern below it (first-match-wins in _PATTERNS)."""
    msg = (
        "litellm.APIError: APIError: OpenAIException - <html>"
        "<head><title>403 Forbidden</title></head>"
        "<body><center><h1>403 Forbidden</h1></center></body></html>"
        " LiteLLM Retried: 3 times"
    )
    r = classify(msg)
    assert r["category"] == "permission_denied", r
    assert r["auto_retryable"] is False, r
    # And the raw PermissionDeniedError class name should hit the same:
    r2 = classify("openai.PermissionDeniedError: <html>403 Forbidden</html>")
    assert r2["category"] == "permission_denied"
    assert r2["auto_retryable"] is False


def test_api_error_html_body_is_transient():
    """litellm.APIError + OpenAIException HTML body — observed 2026-05-24
    when the LLM proxy returned an error page instead of JSON. Must classify
    as service_unavailable so auto-resume + escalation fire (without this,
    the FE looped 15+ times against a hard-down upstream)."""
    for msg in (
        "litellm.APIError: APIError: OpenAIException - <html>",
        "APIConnectionError: peer reset",
        "litellm.APIConnectionError: connect timed out",
    ):
        r = classify(msg)
        assert r["category"] == "service_unavailable", msg
        assert r["auto_retryable"] is True, msg


def test_max_output_limit():
    """The ADK 'Last event shouldn't be partial' pattern."""
    r = classify("Last event shouldn't be partial. LLM max output limit may be reached.")
    assert r["category"] == "max_output_limit"
    assert r["auto_retryable"] is True


def test_unknown_falls_back_safely():
    r = classify("some completely unrelated error message")
    assert r["category"] == "unknown"
    assert r["severity"] == "unknown"
    assert r["auto_retryable"] is False


def test_empty_string_handled():
    r = classify("")
    assert r["category"] == "unknown"
    assert r["auto_retryable"] is False


def test_none_handled():
    r = classify(None)  # type: ignore[arg-type]
    assert r["category"] == "unknown"


@pytest.mark.parametrize("phrase,expected_category", [
    ("blocked by content safety filters", "content_policy"),
    ("configured LLM model was not found", "not_found"),
    ("access to the LLM model was denied", "permission_denied"),
    ("LLM usage budget has been exceeded", "budget_exceeded"),
    ("Unable to connect to the LLM service", "api_connection"),
    ("request to the LLM service timed out", "timeout"),
    ("LLM service encountered an internal error", "internal_server"),
    ("LLM service rejected the request", "bad_request"),
])
def test_each_sam_category_round_trips(phrase, expected_category):
    """Every SAM-friendly message constant maps to its dedicated category."""
    r = classify(phrase)
    assert r["category"] == expected_category, f"phrase={phrase!r}"


def test_classification_is_case_insensitive():
    """SAM doesn't promise message casing — match should tolerate either."""
    upper = classify("THE CONVERSATION HISTORY HAS BECOME TOO LONG FOR THE AI MODEL")
    lower = classify("the conversation history has become too long for the ai model")
    assert upper["category"] == lower["category"] == "context_limit"
