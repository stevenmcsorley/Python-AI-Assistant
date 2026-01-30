from __future__ import annotations

import hashlib
import time

import psycopg
from psycopg.types.json import Json

from .models import Suggestion


class SuggestionWriter:
    def __init__(self, dsn: str, actor_id: str) -> None:
        self._dsn = dsn
        self._actor_id = actor_id

    def write(self, suggestion: Suggestion) -> tuple[str, bool]:
        suggestion.validate()
        with psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT suggestion_id
                        FROM suggestions
                        WHERE intent_id = %s AND type = %s
                        LIMIT 1
                        """,
                        (suggestion.intent_id, suggestion.type),
                    )
                    existing = cur.fetchone()
                    if existing:
                        return str(existing[0]), False

                    cur.execute(
                        """
                        INSERT INTO suggestions (
                            user_id,
                            signal_id,
                            intent_id,
                            type,
                            confidence,
                            rationale,
                            status,
                            created_at,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, now(), now()
                        )
                        RETURNING suggestion_id
                        """,
                        (
                            suggestion.user_id,
                            suggestion.signal_id,
                            suggestion.intent_id,
                            suggestion.type,
                            suggestion.confidence,
                            suggestion.rationale,
                            suggestion.status,
                        ),
                    )
                    suggestion_id = str(cur.fetchone()[0])
                    self._audit_suggestion_created(cur, suggestion_id)
                    return suggestion_id, True

    def _audit_suggestion_created(self, cur: psycopg.Cursor, suggestion_id: str) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:suggestion_created:{suggestion_id}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()
        cur.execute(
            """
            INSERT INTO audit_log (
                actor_type,
                actor_id,
                action_type,
                entity_type,
                entity_id,
                audit_hash,
                metadata
            ) VALUES (
                'orchestrator',
                %s,
                'suggestion_created',
                'suggestion',
                %s,
                %s,
                %s
            )
            """,
            (self._actor_id, suggestion_id, digest, Json({"source": "suggestion_generation"})),
        )
