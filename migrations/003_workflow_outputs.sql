CREATE TABLE IF NOT EXISTS workflow_outputs (
    workflow_output_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL UNIQUE REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    output_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_outputs_workflow_id
    ON workflow_outputs (workflow_id);
