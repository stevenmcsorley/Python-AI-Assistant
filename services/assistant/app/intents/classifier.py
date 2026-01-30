from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..signals.models import Signal
from .models import Intent


class IntentClassifier(ABC):
    @abstractmethod
    def classify(self, signal: Signal, signal_id: str) -> List[Intent]:
        raise NotImplementedError


class RuleBasedIntentClassifier(IntentClassifier):
    def classify(self, signal: Signal, signal_id: str) -> List[Intent]:
        intents: list[Intent] = []
        source_ref = signal.source_ref.lower()
        summary = (signal.summary or "").lower()

        if "job" in source_ref:
            intents.append(
                Intent(
                    user_id=signal.user_id,
                    signal_id=signal_id,
                    intent_type="job_search_interest",
                    confidence=0.7,
                    rationale="source_ref contains 'job'",
                    status="proposed",
                )
            )

        if signal.source_type == "calendar" and "interview" in summary:
            intents.append(
                Intent(
                    user_id=signal.user_id,
                    signal_id=signal_id,
                    intent_type="interview_event",
                    confidence=0.8,
                    rationale="calendar signal summary contains 'interview'",
                    status="proposed",
                )
            )

        if signal.source_type == "note" and "goal" in summary:
            intents.append(
                Intent(
                    user_id=signal.user_id,
                    signal_id=signal_id,
                    intent_type="planning_goal",
                    confidence=0.6,
                    rationale="note signal summary contains 'goal'",
                    status="proposed",
                )
            )

        return intents
