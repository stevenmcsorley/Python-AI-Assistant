from __future__ import annotations

import hashlib
import time

import psycopg
from psycopg.types.json import Json

from .models import Intent


class IntentWriter:
    def __init__(self, dsn: str, actor_id: str) -> None:
        self._dsn = dsn
        self._actor_id = actor_id

    def write(self, intent: Intent) -> tuple[str, bool]:
        intent.validate()
        with psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT intent_id
                        FROM intents
                        WHERE signal_id = %s AND intent_type = %s
                        LIMIT 1
                        """,
                        (intent.signal_id, intent.intent_type),
                    )
                    existing = cur.fetchone()
                    if existing:
                        return str(existing[0]), False

                    cur.execute(
                        """
                        INSERT INTO intents (
                            user_id,
                            signal_id,
                            intent_type,
                            confidence,
                            rationale,
                            status,
                            created_at,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, now(), now()
                        )
                        RETURNING intent_id
                        """,
                        (
                            intent.user_id,
                            intent.signal_id,
                            intent.intent_type,
                            intent.confidence,
                            intent.rationale,
                            intent.status,
                        ),
                    )
                    intent_id = str(cur.fetchone()[0])
                    self._audit_intent_proposed(cur, intent_id)
                    return intent_id, True

    def _audit_intent_proposed(self, cur: psycopg.Cursor, intent_id: str) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:intent_proposed:{intent_id}:{time.time_ns()}".encode("utf-8")
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
                'intent_proposed',
                'intent',
                %s,
                %s,
                %s
            )
            """,
            (self._actor_id, intent_id, digest, Json({"source": "intent_detection"})),
        )
