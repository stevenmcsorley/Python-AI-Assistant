from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Intent:
    user_id: str
    signal_id: str
    intent_type: str
    confidence: float
    rationale: Optional[str]
    status: str = "proposed"

    def validate(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.signal_id:
            raise ValueError("signal_id is required")
        if not self.intent_type:
            raise ValueError("intent_type is required")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.confidence >= 1.0:
            raise ValueError("confidence must be < 1.0 for hypotheses")
        if not self.status:
            raise ValueError("status is required")
