from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..intents.models import Intent
from ..signals.models import Signal
from .models import Suggestion


class SuggestionGenerator(ABC):
    @abstractmethod
    def generate(self, intent: Intent, intent_id: str, signal: Signal) -> Optional[Suggestion]:
        raise NotImplementedError


class RuleBasedSuggestionGenerator(SuggestionGenerator):
    def generate(self, intent: Intent, intent_id: str, signal: Signal) -> Optional[Suggestion]:
        if intent.status != "proposed":
            return None

        base_confidence = min(intent.confidence, 0.9)

        if intent.intent_type == "job_search_interest":
            rationale = (
                f"Signal '{signal.source_ref}' appears job-related. "
                "Would you like to track job search activity or update your status?"
            )
            return Suggestion(
                user_id=intent.user_id,
                intent_id=intent_id,
                signal_id=intent.signal_id,
                type="clarify_job_search",
                confidence=base_confidence,
                rationale=rationale,
                status="queued",
            )

        if intent.intent_type == "interview_event":
            rationale = (
                f"Calendar signal suggests an interview: '{signal.summary}'. "
                "Would you like preparation notes?"
            )
            return Suggestion(
                user_id=intent.user_id,
                intent_id=intent_id,
                signal_id=intent.signal_id,
                type="offer_interview_prep",
                confidence=base_confidence,
                rationale=rationale,
                status="queued",
            )

        if intent.intent_type == "planning_goal":
            rationale = (
                f"Note update mentions a goal: '{signal.summary}'. "
                "Would you like to review or plan next steps?"
            )
            return Suggestion(
                user_id=intent.user_id,
                intent_id=intent_id,
                signal_id=intent.signal_id,
                type="offer_goal_planning",
                confidence=base_confidence,
                rationale=rationale,
                status="queued",
            )

        return None
