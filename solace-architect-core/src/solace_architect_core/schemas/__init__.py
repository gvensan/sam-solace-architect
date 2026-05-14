"""YAML schemas for shared engagement state.

All schemas are dataclasses for simplicity. They serialize round-trip with PyYAML.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Literal, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Decisions ----------

@dataclass
class DecisionEntry:
    """A user/agent decision recorded during an engagement (D-numbered)."""
    id: str                              # D1, D2, ...
    context: str                          # what was being decided
    recommendation: str                   # what was recommended
    selected: str                         # what was selected
    rationale: str                        # why
    source_agent: str
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Review findings ----------

Severity = Literal["critical", "important", "advisory"]
FindingStatus = Literal["pending", "applied", "deferred"]


@dataclass
class FindingEntry:
    """A reviewer finding (F-numbered)."""
    id: str                              # F1, F2, ...
    severity: Severity
    description: str
    affected_artifact: str
    recommendation: str
    source_agent: str                    # which reviewer produced it
    status: FindingStatus = "pending"
    resolution_note: Optional[str] = None
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Open items ----------

OpenItemSeverity = Literal["blocking", "advisory"]
OpenItemSource = Literal["intake", "discovery", "review-deferred", "validation", "provisioning"]
OpenItemStatus = Literal["open", "resolved"]


@dataclass
class OpenItemEntry:
    """A blocking or advisory item that needs the user's attention (Q-numbered)."""
    id: str                              # Q1, Q2, ...
    severity: OpenItemSeverity
    source: OpenItemSource
    description: str
    affecting_step: Optional[str] = None
    affected_artifact: Optional[str] = None
    status: OpenItemStatus = "open"
    source_agent: str = ""
    resolution_note: Optional[str] = None
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Feedback ----------

FeedbackCategory = Literal["accuracy", "depth", "voice", "completeness", "other"]


@dataclass
class FeedbackEntry:
    """User feedback on agent output (FB-numbered). Phase 1 collection only."""
    id: str                              # FB1, FB2, ...
    scope: str                            # which agent/skill the feedback is about
    rating: int                           # 1-5
    category: FeedbackCategory
    note: str
    recorded_by: str = "anonymous"
    recorded_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Project registry ----------

ProjectStatus = Literal["active", "archived"]


@dataclass
class ProjectEntry:
    """Multi-project registry (stored under reserved __system__ engagement)."""
    id: str                              # engagement_id
    name: str
    status: ProjectStatus = "active"
    owner: str = "anonymous"
    description: Optional[str] = None
    created_at: str = field(default_factory=_now)
    last_active_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- EP provisioning state ----------

ProvisioningStatus = Literal["complete", "partial", "failed"]


@dataclass
class ProvisionedObjectEntry:
    """Single EP object created or reused."""
    layer: str                           # application_domains | schemas | events | applications
    name: str
    ep_id: str
    created: bool                         # True = created; False = reused
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)
