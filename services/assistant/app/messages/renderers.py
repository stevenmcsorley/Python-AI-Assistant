from __future__ import annotations

HELP_TEXT = (
    "Supported commands: approve <suggestion_id>, deny <suggestion_id>, "
    "status <workflow_id>, help"
)


def render_message_text(message: dict) -> str:
    message_type = str(message.get("message_type") or "").lower()
    body = (message.get("body") or "").strip()
    related_id = str(message.get("related_entity_id") or "").strip()

    if message_type == "suggestion_ready":
        suffix = ""
        if related_id:
            suffix = (
                f" Reply 'approve {related_id}' to proceed or 'deny {related_id}' to dismiss."
            )
        return f"{body}{suffix}".strip()

    if message_type == "workflow_started":
        if related_id:
            return f"{body} (workflow {related_id})".strip()
        return body

    if message_type == "workflow_completed":
        if related_id:
            return f"{body} (workflow {related_id})".strip()
        return body

    if message_type == "workflow_status":
        return body

    if message_type == "help":
        return HELP_TEXT

    return body
