-- NULL keeps server defaults for users who have not saved their own policy.
-- An explicit JSON null for processing_sla_seconds disables the personal limit.
ALTER TABLE users ADD COLUMN IF NOT EXISTS quality_settings JSONB;
