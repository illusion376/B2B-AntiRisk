-- Persist the model before enqueueing; parallel documents can use different models.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS llm_model VARCHAR(200);
