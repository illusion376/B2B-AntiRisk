CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users(
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    company_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'USER',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    analysis_status VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    progress INT DEFAULT 0,
    risk_score INT DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

DROP TRIGGER IF EXISTS trigger_analyses_updated_at ON analyses;
CREATE TRIGGER trigger_analyses_updated_at
    BEFORE UPDATE ON analyses
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS documents(
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL DEFAULT '',
    file_path TEXT NOT NULL,
    total_pages INT DEFAULT 1,
    is_scanned BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP

);
CREATE INDEX IF NOT EXISTS idx_documents_analysis_id ON documents(analysis_id);

CREATE TABLE IF NOT EXISTS document_chunks(
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    clause_title VARCHAR(255),
    content TEXT NOT NULL,
    embedding vector(1024),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_analysis_id ON document_chunks(analysis_id);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
ON document_chunks
USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS risk_rules(
    id VARCHAR(50) PRIMARY KEY,
    law_type VARCHAR(20) NOT NULL DEFAULT 'ALL',
    category VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    semantic_query TEXT NOT NULL,
    llm_prompt TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS risk_findings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID REFERENCES analyses(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    rule_id VARCHAR(50) REFERENCES risk_rules(id) ON DELETE SET NULL,
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    page_number INT NOT NULL,
    clause VARCHAR(255),
    exact_quote TEXT NOT NULL,
    comment TEXT NOT NULL,
    counter_proposal TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_findings_analysis_id ON risk_findings(analysis_id);


CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);

CREATE OR REPLACE FUNCTION match_document_chunks (
    query_embedding vector(1024),
    target_analysis_id UUID,
    match_limit INT DEFAULT 3
)
RETURNS TABLE (
    chunk_id UUID,
    document_id UUID,
    page_number INT,
    clause_title VARCHAR,
    content TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id AS chunk_id,
        dc.document_id,
        dc.page_number,
        dc.clause_title,
        dc.content,
        (1 - (dc.embedding <=> query_embedding))::FLOAT AS similarity
    FROM document_chunks dc
    WHERE dc.analysis_id = target_analysis_id
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_limit;
END;
$$;


INSERT INTO users (id, email, full_name, company_name, role)
VALUES
(
    '00000000-0000-0000-0000-000000000001',
    'demo_analyst@b2b-center.ru',
    'Кирилл Иванов (Аналитик)',
    'ООО Поставщик-Сервис',
    'USER'
)
ON CONFLICT (email) DO NOTHING;

