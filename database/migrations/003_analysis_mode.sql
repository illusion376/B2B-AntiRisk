

ALTER TABLE documents ADD COLUMN IF NOT EXISTS analysis_mode VARCHAR(20)
    CHECK (analysis_mode IN ('llm', 'nli', 'keyword'));
