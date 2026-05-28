"""Bundled artifact read — one tool call instead of ~20.

The reviewer agents (architect/developer/ops/security), validation, and blueprint
each read roughly the full set of design artifacts in a single task. Done as
individual ``read_artifact`` calls that's ~N model round-trips (each = a request
turn + a consume turn), and the consume turns are where the gateway stalls.

``build_artifact_bundle`` reads them all in ONE call and returns a single
structured payload, so the agent spends one round-trip on inputs instead of N.
This is the read-side of the pre-injection lever: the orchestrator/entrypoint
can call it and inject the bundle into the kickoff, or expose it as a tool the
agent calls once.

The per-artifact cap keeps the bundle from itself becoming a stall-prone giant
payload — same discipline as the grounding excerpt pack.
"""

from __future__ import annotations

from typing import Optional

from .._storage import read_text
from .._user_context import scoped_user

# The artifacts the design phase produces — the consumption set for review /
# validation / blueprint. Absent ones are simply skipped (not every engagement
# uses every scope).
DESIGN_ARTIFACTS: tuple[str, ...] = (
    "topic-design/topic-taxonomy.yaml",
    "broker-select/broker-recommendation.yaml",
    "protocol-select/protocol-map.yaml",
    "integration/integration-map.yaml",
    "mesh-design/dmr-topology.yaml",
    "ha-dr/ha-dr-design.yaml",
    "sam-design/sam-topology.yaml",
    "event-portal/event-portal-model.yaml",
    "migration/migration-plan.yaml",
)

_DEFAULT_CAP = 8000


def build_artifact_bundle(engagement_id: str,
                          names: Optional[tuple[str, ...]] = None,
                          *, user_id: Optional[str] = None,
                          max_chars_each: int = _DEFAULT_CAP) -> dict:
    """Read several artifacts in one shot.

    Returns ``{engagement_id, artifacts:{name:text}, present:[...], missing:[...],
    truncated:[...], count}``. Absent artifacts are reported in ``missing`` (not
    an error — scopes are optional). Read errors are captured inline so one bad
    artifact never sinks the whole bundle.
    """
    names = names or DESIGN_ARTIFACTS
    artifacts: dict[str, str] = {}
    present: list[str] = []
    missing: list[str] = []
    truncated: list[str] = []

    def _read_one(name: str) -> None:
        try:
            txt = read_text(engagement_id, name)
        except FileNotFoundError:
            missing.append(name)
            return
        except Exception as e:  # pragma: no cover - defensive
            artifacts[name] = f"<error reading {name}: {e}>"
            present.append(name)
            return
        if max_chars_each and len(txt) > max_chars_each:
            txt = txt[:max_chars_each] + "\n…<truncated>"
            truncated.append(name)
        artifacts[name] = txt
        present.append(name)

    if user_id:
        with scoped_user(user_id):
            for n in names:
                _read_one(n)
    else:
        for n in names:
            _read_one(n)

    return {
        "engagement_id": engagement_id,
        "artifacts": artifacts,
        "present": present,
        "missing": missing,
        "truncated": truncated,
        "count": len(present),
    }


def render_bundle_block(bundle: dict) -> str:
    """Render a bundle as a single fenced text block for kickoff injection."""
    lines = [f"--- DESIGN ARTIFACTS ({bundle.get('count', 0)} present) ---"]
    for name in bundle.get("present", []):
        lines.append(f"\n### {name}\n{bundle['artifacts'].get(name, '')}")
    if bundle.get("missing"):
        lines.append(f"\n(not produced: {', '.join(bundle['missing'])})")
    return "\n".join(lines)
