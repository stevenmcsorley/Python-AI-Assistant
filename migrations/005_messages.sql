CREATE TABLE IF NOT EXISTS messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    message_type TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    related_entity_type TEXT NOT NULL,
    related_entity_id UUID NOT NULL,
    rendered_text TEXT NULL,
    sent_at TIMESTAMPTZ NULL,
    error_details TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
