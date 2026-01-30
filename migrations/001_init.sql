-- PostgreSQL Schema – Python AI Assistant (v1)

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE workflow_type AS ENUM (
    'planning_day',
    'planning_week',
    'planning_month',
    'event_preparation',
    'research',
    'signal_processing',
    'maintenance'
);

-- Users
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Workflows
CREATE TABLE workflows (
    workflow_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    type workflow_type NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    current_step_id UUID NULL,
    checkpoint_id UUID NULL,
    lease_owner TEXT NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error_details TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending','scheduled','running','paused','completed','failed','cancelled'))
);

-- Workflow checkpoints (immutable)
CREATE TABLE workflow_checkpoints (
    checkpoint_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    step_name TEXT NOT NULL,
    state_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL
);

-- Workflow steps
CREATE TABLE workflow_steps (
    step_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    step_key TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    input_json JSONB NULL,
    output_json JSONB NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error_details TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending','scheduled','running','paused','completed','failed','cancelled')),
    UNIQUE (workflow_id, step_key),
    UNIQUE (workflow_id, step_index),
    UNIQUE (workflow_id, idempotency_key)
);

-- Link workflow.current_step_id and workflows.checkpoint_id now that tables exist
ALTER TABLE workflows
    ADD CONSTRAINT workflows_current_step_fk
    FOREIGN KEY (current_step_id) REFERENCES workflow_steps(step_id) ON DELETE SET NULL;

ALTER TABLE workflows
    ADD CONSTRAINT workflows_checkpoint_fk
    FOREIGN KEY (checkpoint_id) REFERENCES workflow_checkpoints(checkpoint_id) ON DELETE SET NULL;

-- Tasks (jobs)
CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    step_id UUID NULL REFERENCES workflow_steps(step_id) ON DELETE SET NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    input_json JSONB NULL,
    output_json JSONB NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error_details TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending','scheduled','running','paused','completed','failed','cancelled')),
    UNIQUE (workflow_id, idempotency_key)
);

-- Task attempts (immutable)
CREATE TABLE task_attempts (
    task_attempt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ NULL,
    error_details TEXT NULL,
    CHECK (status IN ('running','completed','failed')),
    UNIQUE (task_id, attempt_number)
);

-- Jobs (scheduled background jobs)
CREATE TABLE jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    next_run_at TIMESTAMPTZ NULL,
    last_run_at TIMESTAMPTZ NULL,
    payload_json JSONB NULL,
    lease_owner TEXT NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('scheduled','running','paused','completed','failed')),
    CHECK (schedule_type IN ('cron','interval','once'))
);

-- Signals
CREATE TABLE signals (
    signal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    summary TEXT NULL,
    raw_json JSONB NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('new','processed','ignored'))
);

-- Intents
CREATE TABLE intents (
    intent_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    signal_id UUID NOT NULL REFERENCES signals(signal_id) ON DELETE CASCADE,
    intent_type TEXT NOT NULL,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0.0,
    rationale TEXT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('proposed','confirmed','rejected'))
);

-- Suggestions
CREATE TABLE suggestions (
    suggestion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    signal_id UUID NULL REFERENCES signals(signal_id) ON DELETE SET NULL,
    intent_id UUID NULL REFERENCES intents(intent_id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0.0,
    rationale TEXT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('queued','sent','accepted','dismissed','snoozed'))
);

-- Approvals (immutable)
CREATE TABLE approvals (
    approval_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    suggestion_id UUID NULL REFERENCES suggestions(suggestion_id) ON DELETE SET NULL,
    intent_id UUID NULL REFERENCES intents(intent_id) ON DELETE SET NULL,
    workflow_id UUID NULL REFERENCES workflows(workflow_id) ON DELETE SET NULL,
    decision TEXT NOT NULL,
    channel TEXT NOT NULL,
    reason TEXT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decision IN ('approved','denied','revoked'))
);

-- Artifacts
CREATE TABLE artifacts (
    artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    workflow_id UUID NULL REFERENCES workflows(workflow_id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'prepared',
    current_version_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('prepared','draft','approved','archived'))
);

-- Artifact versions (immutable)
CREATE TABLE artifact_versions (
    artifact_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    state TEXT NOT NULL,
    obsidian_path TEXT NOT NULL,
    content_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    frontmatter_hash TEXT NULL,
    model_provider TEXT NULL,
    model_name TEXT NULL,
    model_version TEXT NULL,
    confidence NUMERIC(4,3) NULL,
    created_by TEXT NOT NULL,
    workflow_id UUID NULL REFERENCES workflows(workflow_id) ON DELETE SET NULL,
    task_id UUID NULL REFERENCES tasks(task_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (state IN ('prepared','draft','approved','archived')),
    UNIQUE (artifact_id, version_number)
);

-- Link artifacts.current_version_id now that artifact_versions exists
ALTER TABLE artifacts
    ADD CONSTRAINT artifacts_current_version_fk
    FOREIGN KEY (current_version_id) REFERENCES artifact_versions(artifact_version_id) ON DELETE SET NULL;

-- Sources (immutable)
CREATE TABLE sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash TEXT NOT NULL,
    snapshot_ref TEXT NULL,
    metadata JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Artifact to Source links (immutable)
CREATE TABLE artifact_sources (
    artifact_version_id UUID NOT NULL REFERENCES artifact_versions(artifact_version_id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
    PRIMARY KEY (artifact_version_id, source_id)
);

-- Memory items (immutable; versioned via supersedes_memory_id)
CREATE TABLE memory_items (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    memory_type TEXT NOT NULL,
    source_id UUID NULL REFERENCES sources(source_id) ON DELETE SET NULL,
    artifact_version_id UUID NULL REFERENCES artifact_versions(artifact_version_id) ON DELETE SET NULL,
    content_ref TEXT NOT NULL,
    summary TEXT NULL,
    confidence NUMERIC(4,3) NULL,
    status TEXT NOT NULL DEFAULT 'active',
    supersedes_memory_id UUID NULL REFERENCES memory_items(memory_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (memory_type IN ('episodic','semantic')),
    CHECK (status IN ('active','deprecated'))
);

-- Memory embeddings (immutable)
CREATE TABLE memory_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id UUID NOT NULL REFERENCES memory_items(memory_id) ON DELETE CASCADE,
    artifact_version_id UUID NULL REFERENCES artifact_versions(artifact_version_id) ON DELETE SET NULL,
    model_name TEXT NOT NULL,
    dims INTEGER NOT NULL,
    embedding VECTOR NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    chunk_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tool executions (immutable)
CREATE TABLE tool_executions (
    tool_exec_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    sandbox_type TEXT NOT NULL,
    status TEXT NOT NULL,
    input_ref TEXT NULL,
    output_ref TEXT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ NULL,
    exit_code INTEGER NULL,
    resource_usage JSONB NULL,
    CHECK (status IN ('running','completed','failed'))
);

-- Audit log (immutable)
CREATE TABLE audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID NULL,
    workflow_id UUID NULL REFERENCES workflows(workflow_id) ON DELETE SET NULL,
    step_id UUID NULL REFERENCES workflow_steps(step_id) ON DELETE SET NULL,
    task_id UUID NULL REFERENCES tasks(task_id) ON DELETE SET NULL,
    job_id UUID NULL REFERENCES jobs(job_id) ON DELETE SET NULL,
    tool_exec_id UUID NULL REFERENCES tool_executions(tool_exec_id) ON DELETE SET NULL,
    input_ref TEXT NULL,
    output_ref TEXT NULL,
    reasoning_ref TEXT NULL,
    before_hash TEXT NULL,
    after_hash TEXT NULL,
    prev_audit_hash TEXT NULL,
    audit_hash TEXT NOT NULL,
    metadata JSONB NULL
);

-- Indexes for workflow resumption
CREATE INDEX idx_workflows_status_lease ON workflows (status, lease_expires_at);
CREATE INDEX idx_workflow_steps_status_lease ON workflow_steps (status, lease_expires_at);
CREATE INDEX idx_tasks_status_lease ON tasks (status, lease_expires_at);
CREATE INDEX idx_jobs_status_next_run ON jobs (status, next_run_at);

-- Recent activity
CREATE INDEX idx_workflows_updated_at ON workflows (updated_at DESC);
CREATE INDEX idx_tasks_updated_at ON tasks (updated_at DESC);
CREATE INDEX idx_signals_received_at ON signals (received_at DESC);
CREATE INDEX idx_suggestions_created_at ON suggestions (created_at DESC);

-- Traceability
CREATE INDEX idx_audit_workflow_time ON audit_log (workflow_id, timestamp DESC);
CREATE INDEX idx_audit_task_time ON audit_log (task_id, timestamp DESC);
CREATE INDEX idx_audit_entity ON audit_log (entity_type, entity_id);
CREATE INDEX idx_tool_exec_task_time ON tool_executions (task_id, started_at DESC);

-- Memory retrieval
CREATE INDEX idx_memory_type_created ON memory_items (memory_type, created_at DESC);
CREATE INDEX idx_memory_user_created ON memory_items (user_id, created_at DESC);

-- Immutability enforcement
CREATE OR REPLACE FUNCTION prevent_update_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'immutable table: %', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

-- Apply immutability triggers
CREATE TRIGGER immut_workflow_checkpoints
    BEFORE UPDATE OR DELETE ON workflow_checkpoints
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_task_attempts
    BEFORE UPDATE OR DELETE ON task_attempts
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_artifact_versions
    BEFORE UPDATE OR DELETE ON artifact_versions
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_sources
    BEFORE UPDATE OR DELETE ON sources
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_artifact_sources
    BEFORE UPDATE OR DELETE ON artifact_sources
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_memory_embeddings
    BEFORE UPDATE OR DELETE ON memory_embeddings
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_approvals
    BEFORE UPDATE OR DELETE ON approvals
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_tool_executions
    BEFORE UPDATE OR DELETE ON tool_executions
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

CREATE TRIGGER immut_audit_log
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();
