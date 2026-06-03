"""Static guard: EP's resume-idempotency and chunked-write rules can't silently regress.

Background — why this test is text-level:
On 2026-06-03, EP hung in a ~60s-per-attempt ReadTimeout retry loop on
neo-supply-chain-tracking. provisioned.yaml + provisioning-report.md already
existed on disk from a prior run, but the agent was re-generating the report
as a single large write_artifact(content=…) payload. LiteLLM's per-chunk
30s ReadTimeout fired before the model finished streaming the content, the
framework retried the same oversize call, and EP never reached its final
set_step_status. The fix is prompt-only (no core code change):
  - HARD RULE caps every write/append payload at 800 words / 5 KB.
  - Resume rule (4) requires SKIPPING the report write when the report
    already exists with non-trivial content — straight to set_step_status.

No JS / runtime harness would catch silent removal of these prompt rules,
so a grep-level guard is the cheapest insurance against re-triggering the
same hang. Locks down:
  * The HARD RULE block names the 800-word / 5 KB cap.
  * The skeleton-first pattern is documented with the 150-word skeleton cap.
  * The Resume-aware section warns about ReadTimeout AS the failure mode.
  * The skip-if-report-exists branch is named in the resume rule list.
  * Step 9 (final outputs) mentions both the HARD RULE and the skip-if-exists
    behaviour so a worker reading just step 9 doesn't miss it.
"""

from __future__ import annotations

from pathlib import Path


_CFG = (Path(__file__).resolve().parents[1]
        / "plugins" / "solace-architect-event-portal" / "config.yaml")


def _read() -> str:
    return _CFG.read_text(encoding="utf-8")


def test_ep_hard_rule_section_present_with_800_word_cap():
    """The HARD RULE block must name the 800-word / 5 KB cap. Without the
    specific numbers the cap silently drifts and the next 1500-word reset
    re-triggers the ReadTimeout hang."""
    src = _read()
    assert "# HARD RULE" in src, "HARD RULE section missing in EP prompt"
    assert "≤ 800 words" in src or "<= 800 words" in src
    assert "5 KB" in src or "5KB" in src
    # Provenance — name the symptom so a future reader sees the link.
    assert "ReadTimeout" in src


def test_ep_skeleton_first_pattern_documented():
    """The provisioning-report.md skeleton-first pattern is the load-bearing
    detail that makes the first write atomic-tiny. If the prompt loses this,
    the agent will compose long initial writes again."""
    src = _read()
    assert "SKELETON" in src or "skeleton" in src
    assert "150 words" in src


def test_ep_resume_rule_skips_existing_report():
    """Rule (4) of resume MUST say 'report present + provisioned present →
    skip the report write'. This is what unblocks the agent from the retry
    loop when it resumes a project where the prior run wrote both."""
    src = _read()
    # Anchor on the resume-rule list.
    idx = src.find("# Resume-aware re-entry")
    assert idx >= 0
    window = src[idx : idx + 2500]
    assert "(4)" in window or "Rule 4" in window or "rule 4" in window
    # The literal skip-if-exists branch.
    assert "SKIP the report" in window or "skip the report write" in window.lower()
    # And the read warning about non-trivial existing content.
    assert "already exists" in window.lower() and "rewrite" in window.lower()


def test_ep_step_9_references_hard_rule_and_skip():
    """Step 9 must remind the agent of both the HARD RULE chunking AND the
    skip-if-exists branch. A worker reading only step 9 (a common path under
    auto-mode resume) should still know to apply both rules."""
    src = _read()
    idx = src.find("9. Final outputs")
    assert idx >= 0, "step 9 anchor missing"
    window = src[idx : idx + 800]
    assert "HARD RULE" in window
    assert "skeleton" in window.lower()
    # 800-word append cap reiterated.
    assert "800 words" in window
    # Skip-if-exists pointer to the resume rule.
    assert "SKIP" in window or "skip" in window.lower()


def test_ep_does_not_carry_old_naive_report_rewrite_rule():
    """The pre-fix rule was 'report only missing → rewrite from provisioned.yaml'
    with no size discipline — meant the agent ALWAYS regenerated the report,
    even when it already existed. Catches a partial revert that would
    re-introduce the loop."""
    src = _read()
    bad = "report only missing → rewrite from provisioned.yaml"
    assert bad not in src, (
        f"old report-rewrite rule still present (re-introduces the ReadTimeout "
        f"loop): {bad!r}")
