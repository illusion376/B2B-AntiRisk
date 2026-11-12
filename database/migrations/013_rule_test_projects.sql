-- One hidden test-document workspace per user. Existing projects stay visible.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_rule_test BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_rule_test_user
    ON projects (user_id) WHERE is_rule_test;

-- The hidden workspace must not reserve a name in the user's normal project list.
DROP INDEX IF EXISTS uq_projects_user_title;
CREATE UNIQUE INDEX uq_projects_user_title
    ON projects (user_id, lower(title)) WHERE NOT is_rule_test;
