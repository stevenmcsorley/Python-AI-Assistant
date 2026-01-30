from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Suggestion:
    user_id: str
    intent_id: str
    signal_id: str
    type: str
    confidence: float
    rationale: Optional[str]
    status: str = "queued"

    def validate(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.intent_id:
            raise ValueError("intent_id is required")
        if not self.signal_id:
            raise ValueError("signal_id is required")
        if not self.type:
            raise ValueError("type is required")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.confidence >= 1.0:
            raise ValueError("confidence must be < 1.0 for suggestions")
        if not self.status:
            raise ValueError("status is required")
