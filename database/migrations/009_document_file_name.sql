ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_name VARCHAR(255);

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
