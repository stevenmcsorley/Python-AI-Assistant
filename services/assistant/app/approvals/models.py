from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Approval:
    user_id: str
    suggestion_id: str
    intent_id: Optional[str]
    workflow_id: Optional[str]
    decision: str
    channel: str
    reason: Optional[str]

    def validate(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.suggestion_id:
            raise ValueError("suggestion_id is required")
        if self.decision not in ("approved", "denied"):
            raise ValueError("decision must be 'approved' or 'denied'")
        if not self.channel:
            raise ValueError("channel is required")
