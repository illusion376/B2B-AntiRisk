

ALTER TABLE documents ADD COLUMN IF NOT EXISTS chat_revision UUID NOT NULL DEFAULT uuid_generate_v4();

CREATE TABLE IF NOT EXISTS document_chat_messages (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    context_version VARCHAR(64) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    finding_id UUID REFERENCES risk_findings(id) ON DELETE SET NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    draft_title VARCHAR(255),
    draft_content TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_document_chat_history
    ON document_chat_messages (document_id, user_id, context_version, created_at, id);
