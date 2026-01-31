CREATE TABLE IF NOT EXISTS user_delivery_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    muted BOOLEAN NOT NULL DEFAULT false,
    snoozed_until TIMESTAMPTZ NULL,
    allowed_channels TEXT[] NOT NULL DEFAULT ARRAY['whatsapp'],
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
