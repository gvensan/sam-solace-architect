"""Static guard: Blueprint's per-call size budget stays at 800 words / 5 KB.

Background — why this test is text-level:
On 2026-06-03, Blueprint hung in a 3-min-per-attempt retry loop while writing
``blueprint/architecture-overview.md``. The upstream gateway truncated the
oversize function-call JSON stream — args arrived without their ``content``
field, the framework auto-continued, and the SAME oversize call was retried
indefinitely. The fix is prompt-only (no core code change): the agent now
follows a skeleton-first pattern and every payload is capped at 800 words
/ 5 KB. The previous cap was 1500 words / 8 KB and was too generous.

There is no JS / runtime harness that would catch silent removal of these
prompt rules, so a grep-level guard is the cheapest insurance against
regressing the same hang. Locks down:
  * The HARD RULE block is present at the top of the workflow.
  * The skeleton-first pattern is documented.
  * The per-call size budget literal mentions 800 words / 5 KB.
  * Step 4 references the skeleton-then-append pattern (not the old single-write rule).
"""

from __future__ import annotations

from pathlib import Path


_CFG = (Path(__file__).resolve().parents[1]
        / "plugins" / "solace-architect-blueprint" / "config.yaml")


def _read() -> str:
    return _CFG.read_text(encoding="utf-8")


def test_hard_rule_section_present_with_800_word_cap():
    """The HARD RULE block must be there and must name the 800-word / 5 KB
    cap. Without this section the agent has no upfront reason to chunk;
    without the literal numbers the cap silently drifts."""
    src = _read()
    assert "# HARD RULE" in src, "HARD RULE section missing — the hoisted size budget"
    assert "≤ 800 words" in src or "<= 800 words" in src
    assert "5 KB" in src or "5KB" in src


def test_skeleton_first_pattern_documented():
    """The skeleton-first pattern is what makes the FIRST write_artifact
    call atomic-tiny (impossible to truncate). If the prompt loses this,
    the agent will compose long initial writes again."""
    src = _read()
    assert "Skeleton-first pattern" in src
    # The 150-word skeleton cap must be specific — "small" alone is what
    # the old prompt said and it didn't work.
    assert "150 words" in src


def test_step_4_uses_skeleton_then_append_pattern():
    """Step 4 (architecture narrative) must follow the new
    skeleton-then-append-per-section pattern, NOT the old "first chunk
    then continue" pattern that was ambiguous about per-call size."""
    src = _read()
    idx = src.find("4. Compose architecture narrative")
    assert idx >= 0, "step 4 anchor missing"
    window = src[idx : idx + 2000]
    # The pattern markers (skeleton + per-H2 append) must be inside step 4.
    assert "skeleton" in window.lower()
    assert "append_artifact" in window
    assert "ONE PER TURN" in window or "one per turn" in window.lower()


def test_per_call_size_budget_section_has_tightened_cap():
    """The dedicated 'Per-call size budget' section must reflect the new
    tighter cap (800 words / 5 KB) and document why it was tightened —
    so a future reader doesn't relax it without knowing the history."""
    src = _read()
    idx = src.find("# Per-call size budget")
    assert idx >= 0
    window = src[idx : idx + 800]
    assert "≤ 800 words" in window or "<= 800 words" in window
    assert "5 KB" in window
    # Honest provenance note about WHY this number — keeps anyone tempted
    # to bump it back to 1500 from doing so without context.
    assert "neo-supply-chain-tracking" in window or "2026-06-03" in window


def test_old_1500_word_cap_not_present_as_active_rule():
    """The previous 1500-word/8 KB cap must not survive as an active rule
    (it can be referenced as history in a comment, but not stated as the
    current limit). Catches accidental partial reverts."""
    src = _read()
    # Allow a reference to "1500" inside the provenance note ("the old
    # 1500-word / 8-KB cap was producing payloads that …"); reject any
    # active rule line stating the old limit.
    for active_phrase in (
        "payload < ~1500 words",
        "payload ≤ 1500 words",
        "≤ ~4 KB",                # the older write-then-append cap
    ):
        assert active_phrase not in src, (
            f"old cap phrase still present as an active rule: {active_phrase!r}")
