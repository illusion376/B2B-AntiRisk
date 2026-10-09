-- Профиль сохраняется до постановки задачи в очередь и применяется воркером.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS analysis_sensitivity VARCHAR(20)
    NOT NULL DEFAULT 'balanced'
    CHECK (analysis_sensitivity IN ('strict', 'balanced', 'sensitive'));
