from __future__ import annotations

import requests

from . import DeliveryProvider


class BaileysProvider(DeliveryProvider):
    name = "baileys"

    def deliver(self, message: dict) -> tuple[bool, str | None]:
        text = message.get("rendered_text") or message.get("body") or ""
        if not isinstance(text, str) or not text.strip():
            return False, "empty_message"

        recipient = message.get("to") or message.get("recipient") or message.get("user_id")
        if not recipient:
            return False, "missing_recipient"

        try:
            response = requests.post(
                "http://baileys:3000/send",
                json={"to": str(recipient), "text": text},
                timeout=5,
            )
        except requests.RequestException as exc:
            return False, f"request_error:{exc}"

        if 200 <= response.status_code < 300:
            return True, None
        return False, f"provider_error:{response.status_code}"
