from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class Signal:
    user_id: str
    source_type: str
    source_ref: str
    received_at: datetime
    summary: Optional[str]
    raw_json: Optional[dict[str, Any]]
    status: str = "new"

    def validate(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.source_type:
            raise ValueError("source_type is required")
        if not self.source_ref:
            raise ValueError("source_ref is required")
        if not isinstance(self.received_at, datetime):
            raise ValueError("received_at must be a datetime")
        if not self.status:
            raise ValueError("status is required")
