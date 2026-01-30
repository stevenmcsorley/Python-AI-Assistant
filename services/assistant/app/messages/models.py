from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    user_id: str
    channel: str
    message_type: str
    body: str
    status: str
    related_entity_type: str
    related_entity_id: str
    message_id: str | None = None

    def validate(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.channel:
            raise ValueError("channel is required")
        if not self.message_type:
            raise ValueError("message_type is required")
        if not self.body:
            raise ValueError("body is required")
        if not self.status:
            raise ValueError("status is required")
        if not self.related_entity_type:
            raise ValueError("related_entity_type is required")
        if not self.related_entity_id:
            raise ValueError("related_entity_id is required")
