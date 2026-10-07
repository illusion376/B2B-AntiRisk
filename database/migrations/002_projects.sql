-- Проекты (раздел «Документы» во фронтенде): проект содержит загруженные файлы.
-- Каждый загруженный файл — отдельный анализ (analyses); ZIP-архив — анализ с несколькими документами.

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    title VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- Названия проектов уникальны без учёта регистра (как проверяет фронтенд)
CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_user_title ON projects (user_id, lower(title));

DROP TRIGGER IF EXISTS trigger_projects_updated_at ON projects;
CREATE TRIGGER trigger_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE analyses ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_analyses_project_id ON analyses(project_id, created_at);

-- Уровень риска 'LOW' (низкий риск во фронтенде) хранится в тех же колонках severity:
-- risk_rules.severity: RED | YELLOW | LOW;  risk_findings.severity: RED | YELLOW | LOW | GREEN
