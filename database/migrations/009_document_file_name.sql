-- Добавление колонки file_name в таблицу documents.
-- Используется в backend/app/models.py, uploads.py, api/documents.py и генераторах отчётов.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_name VARCHAR(255);

-- Для существующих документов заполняем file_name из relative_path или file_path
UPDATE documents
SET file_name = SUBSTRING(
    COALESCE(
        NULLIF(regexp_replace(COALESCE(relative_path, file_path), '^.*[/\\]', ''), ''),
        'document'
    ),
    1, 255
)
WHERE file_name IS NULL OR file_name = '';

ALTER TABLE documents ALTER COLUMN file_name SET DEFAULT '';
ALTER TABLE documents ALTER COLUMN file_name SET NOT NULL;
