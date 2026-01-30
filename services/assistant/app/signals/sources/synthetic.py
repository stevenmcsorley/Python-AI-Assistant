from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from ..models import Signal
from ..source import SignalSource


class SyntheticSignalSource(SignalSource):
    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def fetch(self) -> List[Signal]:
        return [
            Signal(
                user_id=self._user_id,
                source_type="synthetic",
                source_ref="calendar:event:team-meeting-2026-02-01",
                received_at=datetime(2026, 2, 1, 9, 0, 0, tzinfo=timezone.utc),
                summary="Team meeting scheduled for Feb 1, 2026 at 9:00 AM",
                raw_json={"type": "calendar", "title": "Team Meeting"},
                status="new",
            ),
            Signal(
                user_id=self._user_id,
                source_type="synthetic",
                source_ref="email:subject:job-offer-example",
                received_at=datetime(2026, 2, 2, 14, 30, 0, tzinfo=timezone.utc),
                summary="Email received: Job offer example",
                raw_json={"type": "email", "subject": "Job Offer Example"},
                status="new",
            ),
            Signal(
                user_id=self._user_id,
                source_type="synthetic",
                source_ref="note:obsidian:project-goal",
                received_at=datetime(2026, 2, 3, 8, 15, 0, tzinfo=timezone.utc),
                summary="Obsidian note updated: Project Goal",
                raw_json={"type": "note", "title": "Project Goal"},
                status="new",
            ),
        ]
