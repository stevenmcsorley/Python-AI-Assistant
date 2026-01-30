from __future__ import annotations

from abc import ABC, abstractmethod


class DeliveryProvider(ABC):
    name: str

    @abstractmethod
    def deliver(self, message: dict) -> tuple[bool, str | None]:
        raise NotImplementedError


class WhatsAppStubProvider(DeliveryProvider):
    name = "whatsapp_stub"

    def deliver(self, message: dict) -> tuple[bool, str | None]:
        text = message.get("rendered_text") or message.get("body") or ""
        if not isinstance(text, str) or not text.strip():
            return False, "empty_message"
        return True, None
