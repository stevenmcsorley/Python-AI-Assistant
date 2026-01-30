from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

import psycopg
from psycopg.types.json import Json

from .models import Signal


class SignalWriter:
    def __init__(self, dsn: str, actor_id: str) -> None:
        self._dsn = dsn
        self._actor_id = actor_id

    def write(self, signal: Signal) -> tuple[str, bool]:
        signal.validate()
        with psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT signal_id
                        FROM signals
                        WHERE source_type = %s AND source_ref = %s
                        LIMIT 1
                        """,
                        (signal.source_type, signal.source_ref),
                    )
                    existing = cur.fetchone()
                    if existing:
                        return str(existing[0]), False

                    cur.execute(
                        """
                        INSERT INTO signals (
                            user_id,
                            source_type,
                            source_ref,
                            received_at,
                            summary,
                            raw_json,
                            status,
                            created_at,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, now(), now()
                        )
                        RETURNING signal_id
                        """,
                        (
                            signal.user_id,
                            signal.source_type,
                            signal.source_ref,
                            signal.received_at,
                            signal.summary,
                            Json(signal.raw_json or {}),
                            signal.status,
                        ),
                    )
                    signal_id = str(cur.fetchone()[0])

                    self._audit_signal_ingested(cur, signal_id)
                    return signal_id, True

    def _audit_signal_ingested(self, cur: psycopg.Cursor, signal_id: str) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:signal_ingested:{signal_id}:{time.time_ns()}".encode("utf-8")
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
                'signal_ingested',
                'signal',
                %s,
                %s,
                %s
            )
            """,
            (self._actor_id, signal_id, digest, Json({"source": "signal_ingestion"})),
        )
