-- Nullable snapshots preserve the distinction between old, unmeasured runs
-- and checks made after quality instrumentation was enabled.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS quality_snapshot JSONB;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_kind VARCHAR(20);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_sla_ms INTEGER;
