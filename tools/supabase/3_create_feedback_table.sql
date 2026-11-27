-- Feedback from the TASO APP Explorer page. Run once in the Supabase SQL Editor. Safe to run again.
--
-- Anyone using the page can add feedback (through the publishable key), but nobody can read,
-- change or delete it through the public key. The team reads it in the Table Editor.

CREATE TABLE IF NOT EXISTS public.site_feedback (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  created_at     timestamptz NOT NULL DEFAULT now(),
  feedback_type  text NOT NULL CHECK (feedback_type IN
                   ('general', 'impact', 'targets', 'interventions', 'provider-info', 'other',
                    'wrong-target', 'missing-target', 'intervention')),  -- the last three: earlier categories, kept for old rows
  institution    text CHECK (length(institution) <= 200),
  detail         text NOT NULL CHECK (length(btrim(detail)) BETWEEN 1 AND 5000),
  email          text CHECK (email IS NULL OR (length(email) <= 320 AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$')),
  page_task      text CHECK (length(page_task) <= 50),   -- which task the person had open
  -- For the team
  status         text NOT NULL DEFAULT 'New' CHECK (status IN ('New', 'In progress', 'Done', 'No action needed')),
  team_notes     text
);
CREATE INDEX IF NOT EXISTS site_feedback_created ON public.site_feedback (created_at);

ALTER TABLE public.site_feedback ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY "Anyone can send feedback" ON public.site_feedback
    FOR INSERT TO anon, authenticated WITH CHECK (status = 'New' AND team_notes IS NULL);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- The public key may only fill in these columns, and may not read the table
REVOKE ALL ON public.site_feedback FROM anon, authenticated;
GRANT INSERT (feedback_type, institution, detail, email, page_task) ON public.site_feedback TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.site_feedback TO service_role;
