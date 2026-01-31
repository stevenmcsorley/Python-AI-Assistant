from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

import psycopg

_LOGGER = logging.getLogger("messages.preferences")


@dataclass(frozen=True)
class UserDeliveryPreferences:
    user_id: str
    muted: bool
    snoozed_until: datetime | None
    allowed_channels: list[str]


def get_user_delivery_preferences(
    cur: psycopg.Cursor,
    user_id: str,
) -> UserDeliveryPreferences:
    if not _preferences_table_exists(cur):
        _LOGGER.warning("user_delivery_preferences table missing; allowing delivery")
        return UserDeliveryPreferences(
            user_id=user_id,
            muted=False,
            snoozed_until=None,
            allowed_channels=["whatsapp"],
        )

    cur.execute(
        """
        SELECT user_id, muted, snoozed_until, allowed_channels
        FROM user_delivery_preferences
        WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return UserDeliveryPreferences(
            user_id=user_id,
            muted=False,
            snoozed_until=None,
            allowed_channels=["whatsapp"],
        )

    if isinstance(row, dict):
        muted = bool(row.get("muted"))
        snoozed_until = row.get("snoozed_until")
        channels = row.get("allowed_channels")
    else:
        _, muted, snoozed_until, channels = row

    allowed_channels = [str(ch).lower() for ch in (channels or [])]
    return UserDeliveryPreferences(
        user_id=user_id,
        muted=muted,
        snoozed_until=snoozed_until,
        allowed_channels=allowed_channels,
    )


def evaluate_delivery_preferences(
    preferences: UserDeliveryPreferences,
    channel: str,
    now: datetime | None = None,
) -> tuple[bool, str | None, int]:
    now = now or datetime.now(timezone.utc)
    channel = channel.lower()

    if preferences.muted:
        return True, "muted", 0

    if preferences.snoozed_until and now < preferences.snoozed_until:
        retry_after = int((preferences.snoozed_until - now).total_seconds())
        return True, "snoozed", max(retry_after, 0)

    if channel not in preferences.allowed_channels:
        return True, "channel_disabled", 0

    return False, None, 0


def _preferences_table_exists(cur: psycopg.Cursor) -> bool:
    cur.execute("SELECT to_regclass('public.user_delivery_preferences')")
    row = cur.fetchone()
    if not row:
        return False
    value = next(iter(row.values())) if isinstance(row, dict) else row[0]
    return value is not None
