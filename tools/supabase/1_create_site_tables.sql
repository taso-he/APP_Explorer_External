-- Public, read-only data for the TASO APP Explorer page (GitHub Pages).
-- Run once in the Supabase SQL Editor. Safe to run again.
--
-- The page reads three things, using the project's publishable key:
--   site_providers      one row per provider with a current plan: place, size, plan link
--   site_targets        a view of targets_cleaned: current plans only, public columns only
--   site_interventions  quality-assured interventions, as published
--
-- The publishable key is public (it sits in the page), so it must only be able to
-- read these three. This file also removes its access to the internal QA tables.

-- 1. Provider context
CREATE TABLE IF NOT EXISTS public.site_providers (
  ukprn          text PRIMARY KEY,
  name           text NOT NULL,
  region         text,
  rap            text,                 -- proposed regional access partnership
  mission_group  text,
  mission_group2 text,
  mission_group3 text,
  ug_students    integer,
  lat            double precision,
  lng            double precision,
  plan_url       text,
  plan_period    text,
  profile        jsonb,                -- % of undergraduates by group, for "similar population" matching
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- 2. Published interventions
CREATE TABLE IF NOT EXISTS public.site_interventions (
  record_id            text PRIMARY KEY,
  ukprn                text NOT NULL,
  intervention_name    text,
  activity_status      text,
  description          text,
  strategies           jsonb,          -- lists, as JSON arrays
  students_targeted    text,
  target_demographics  jsonb,
  lifecycle_stages     jsonb,
  linked_target_ids    jsonb,
  risks                jsonb,
  page                 integer,
  qa_status            text,
  updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS site_interventions_ukprn ON public.site_interventions (ukprn);

-- 3. Targets: current plans only, with the cleaned label where there is one
CREATE OR REPLACE VIEW public.site_targets WITH (security_invoker = true) AS
SELECT ukprn,
       reference_number AS ref,
       lifecycle_stage AS stage,
       coalesce(nullif(characteristic_clean, ''), characteristic) AS characteristic,
       coalesce(nullif(target_group_clean, ''), target_group) AS target_group,
       coalesce(nullif(comparator_group_clean, ''), comparator_group) AS comparator,
       aim,
       description_and_commentary AS description,
       is_this_target_collaborative AS collaborative,
       data_source, units, baseline_year,
       baseline_data AS baseline,
       target, target_year
FROM public.targets_cleaned
WHERE current_plan = 'Yes';

-- Row level security: anyone may read the site tables; nobody may change them through the API
ALTER TABLE public.site_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.site_interventions ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY "Public read" ON public.site_providers FOR SELECT TO anon, authenticated USING (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE POLICY "Public read" ON public.site_interventions FOR SELECT TO anon, authenticated USING (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

GRANT SELECT ON public.site_providers, public.site_interventions, public.site_targets TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.site_providers, public.site_interventions TO service_role;

-- site_targets reads targets_cleaned as the visitor, so the visitor needs to read the
-- columns it uses (and only those: reviewer names and QA notes stay private)
GRANT SELECT (ukprn, reference_number, lifecycle_stage, characteristic, characteristic_clean,
              target_group, target_group_clean, comparator_group, comparator_group_clean, aim,
              description_and_commentary, is_this_target_collaborative, data_source, units,
              baseline_year, baseline_data, target, target_year, current_plan)
  ON public.targets_cleaned TO anon, authenticated;

-- The internal QA tables are for the team only, not the public key
REVOKE SELECT ON public.qa_claude_runs, public.qa_claude_field_reviews,
                 public.qa_claude_record_checks, public.qa_claude_review_summary FROM anon, authenticated;
