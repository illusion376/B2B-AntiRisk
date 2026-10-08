-- NULL сохраняется для старых результатов: их движок достоверно неизвестен.
-- Новый запуск записывает выбранный режим до постановки задачи в очередь.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS analysis_mode VARCHAR(20)
    CHECK (analysis_mode IN ('llm', 'nli', 'keyword'));
