-- Review workflow for the interventions, and a tidy-up of tables no longer in use.
-- Applied 31 Oct 2026. Safe to read; running it twice will fail on the moves, which is expected.
--
-- interventions_working   one row per intervention, holding the corrected values. Reviewers'
--                         decisions are written straight into it.
-- qa_person_checks        the review queue: items a person needs to decide (from Claude's review
--                         now, and from provider contacts or the feedback form later)
-- qa_reviewers            the email addresses allowed to sign in to the review page
-- site_interventions      now a view of interventions_working, so the TASO page shows decisions
--                         as soon as they are made, with awaiting_review set while items are open

-- 1. Archive tables that are no longer in use (kept, readable, out of the way)
CREATE SCHEMA IF NOT EXISTS archive;
ALTER VIEW public.qa_auto_review_summary SET SCHEMA archive;
ALTER TABLE public.targets_extracted SET SCHEMA archive;
ALTER TABLE public.qa_auto_field_reviews SET SCHEMA archive;
ALTER TABLE public.qa_auto_record_checks SET SCHEMA archive;
ALTER TABLE public.qa_missed_interventions SET SCHEMA archive;
ALTER TABLE public.qa_plan_completeness SET SCHEMA archive;
ALTER TABLE public.site_interventions SET SCHEMA archive;
ALTER TABLE archive.site_interventions RENAME TO site_interventions_5_plan_pilot;
REVOKE ALL ON ALL TABLES IN SCHEMA archive FROM anon, authenticated;

-- The public key never needs to empty the raw extraction
REVOKE TRUNCATE, REFERENCES, TRIGGER ON public.extracted_interventions FROM anon, authenticated;

-- 2. The working copy of the interventions (field names as in the extraction)
CREATE TABLE public.interventions_working (
  record_id                         text PRIMARY KEY,
  ukprn                             text NOT NULL,
  provider                          text,
  extraction_run_id                 text,
  intervention_name                 text,
  activity_status                   text,
  intervention_description          text,
  intervention_strategy             text,
  students_targeted_exact           text,
  target_demographics               text,
  demographics_combined             text,
  lifecycle_stages                  text,
  linked_target_ids                 text,
  linked_targets_text               text,
  risks_to_equality_of_opportunity  text,
  page                              text,
  removed                           boolean NOT NULL DEFAULT false,
  removed_reason                    text,
  qa_status                         text,
  loaded_at                         timestamptz NOT NULL DEFAULT now(),
  updated_at                        timestamptz NOT NULL DEFAULT now(),
  updated_by                        text
);
CREATE INDEX interventions_working_ukprn ON public.interventions_working (ukprn);

-- 3. The review queue
CREATE TABLE public.qa_person_checks (
  check_id         text PRIMARY KEY,
  source           text NOT NULL DEFAULT 'claude',      -- claude | provider | feedback
  review_run_id    text,
  kind             text NOT NULL CHECK (kind IN ('field', 'sample', 'removed', 'kept_duplicate', 'record_unsure', 'missing')),
  record_id        text,
  ukprn            text,
  provider         text,
  intervention     text,
  field            text,
  reason           text,
  current_value    text,
  suggested_value  text,
  evidence_quote   text,
  evidence_page    integer,
  status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'rejected', 'edited')),
  final_value      text,
  note             text,
  decided_by       text,
  decided_at       timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qa_person_checks_record ON public.qa_person_checks (record_id);
CREATE INDEX qa_person_checks_open ON public.qa_person_checks (status, ukprn);

CREATE TABLE public.qa_reviewers (email text PRIMARY KEY);
INSERT INTO public.qa_reviewers VALUES ('mikayla.boginsky@taso.org.uk'), ('davidgilani@hotmail.co.uk');

-- 4. Who may review: a signed-in user whose email is on the list
CREATE OR REPLACE FUNCTION public.is_reviewer() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.qa_reviewers WHERE lower(email) = lower(coalesce(auth.jwt() ->> 'email', '')));
$$;

ALTER TABLE public.interventions_working ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qa_person_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qa_reviewers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Reviewers read" ON public.interventions_working FOR SELECT TO authenticated USING (public.is_reviewer());
CREATE POLICY "Reviewers read" ON public.qa_person_checks FOR SELECT TO authenticated USING (public.is_reviewer());
GRANT SELECT ON public.interventions_working, public.qa_person_checks TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.interventions_working, public.qa_person_checks, public.qa_reviewers TO service_role;
-- Reviewers change data only through decide_check below, never by writing to the tables directly

-- 5. Record a decision and apply it to the working copy
CREATE OR REPLACE FUNCTION public.decide_check(p_check_id text, p_decision text, p_value text DEFAULT NULL, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  c public.qa_person_checks;
  who text := auth.jwt() ->> 'email';
  new_value text;
  fields text[] := ARRAY['intervention_name', 'activity_status', 'intervention_description', 'intervention_strategy',
    'students_targeted_exact', 'target_demographics', 'demographics_combined', 'lifecycle_stages', 'linked_target_ids',
    'linked_targets_text', 'risks_to_equality_of_opportunity', 'page'];
BEGIN
  IF NOT public.is_reviewer() THEN RAISE EXCEPTION 'Not on the reviewer list'; END IF;
  IF p_decision NOT IN ('accept', 'reject', 'edit') THEN RAISE EXCEPTION 'Decision must be accept, reject or edit'; END IF;
  SELECT * INTO c FROM public.qa_person_checks WHERE check_id = p_check_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'No such item'; END IF;

  IF c.kind IN ('field', 'sample') THEN
    IF NOT c.field = ANY (fields) THEN RAISE EXCEPTION 'Unknown field %', c.field; END IF;
    -- accept: Claude's value; reject: the value before Claude's suggestion; edit: the reviewer's value
    new_value := CASE p_decision WHEN 'accept' THEN coalesce(nullif(c.suggested_value, ''), c.current_value)
                                 WHEN 'reject' THEN c.current_value
                                 ELSE p_value END;
    EXECUTE format('UPDATE public.interventions_working SET %I = $1, updated_at = now(), updated_by = $2 WHERE record_id = $3', c.field)
      USING new_value, who, c.record_id;
  ELSIF c.kind IN ('removed', 'kept_duplicate', 'record_unsure') THEN
    -- removed / kept_duplicate: accept = leave it out; record_unsure: accept = it is an intervention, keep it
    UPDATE public.interventions_working
       SET removed = CASE WHEN c.kind = 'record_unsure' THEN p_decision = 'reject' ELSE p_decision = 'accept' END,
           removed_reason = CASE WHEN (c.kind = 'record_unsure' AND p_decision = 'reject')
                                   OR (c.kind <> 'record_unsure' AND p_decision = 'accept') THEN c.reason END,
           updated_at = now(), updated_by = who
     WHERE record_id = c.record_id;
  END IF;
  -- 'missing' items change no data: the decision says whether a record needs adding

  UPDATE public.qa_person_checks
     SET status = CASE p_decision WHEN 'accept' THEN 'accepted' WHEN 'reject' THEN 'rejected' ELSE 'edited' END,
         final_value = new_value, note = nullif(p_note, ''), decided_by = who, decided_at = now()
   WHERE check_id = p_check_id;
  RETURN jsonb_build_object('check_id', p_check_id, 'status', p_decision, 'value', new_value);
END $$;
REVOKE ALL ON FUNCTION public.decide_check(text, text, text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.decide_check(text, text, text, text) TO authenticated;

-- 6. What the TASO page reads (first version; replaced by section 7 below)
CREATE OR REPLACE FUNCTION public.json_list(t text) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF t IS NULL OR btrim(t) = '' THEN RETURN '[]'::jsonb; END IF;
  BEGIN
    IF jsonb_typeof(t::jsonb) = 'array' THEN RETURN t::jsonb; END IF;
  EXCEPTION WHEN others THEN NULL;
  END;
  RETURN jsonb_build_array(t);
END $$;

-- Runs with its owner's rights, so the public key can read published interventions without
-- being able to read the working table or the review queue themselves
CREATE VIEW public.site_interventions AS
SELECT w.record_id, w.ukprn, w.intervention_name, nullif(w.activity_status, '') AS activity_status,
       w.intervention_description AS description, public.json_list(w.intervention_strategy) AS strategies,
       w.students_targeted_exact AS students_targeted, public.json_list(w.target_demographics) AS target_demographics,
       public.json_list(w.lifecycle_stages) AS lifecycle_stages, public.json_list(w.linked_target_ids) AS linked_target_ids,
       public.json_list(w.risks_to_equality_of_opportunity) AS risks,
       CASE WHEN w.page ~ '^\d+$' THEN w.page::integer END AS page, w.qa_status,
       EXISTS (SELECT 1 FROM public.qa_person_checks c WHERE c.record_id = w.record_id AND c.status = 'open') AS awaiting_review,
       w.updated_at
FROM public.interventions_working w
WHERE NOT w.removed;
GRANT SELECT ON public.site_interventions TO anon, authenticated;

-- 7. (Second migration, same day) The public view runs with the visitor's own rights. Each record
-- keeps a count of its open review items, so the public never needs to read the review queue.
ALTER TABLE public.interventions_working ADD COLUMN open_checks integer NOT NULL DEFAULT 0;
CREATE OR REPLACE FUNCTION public.recount_open_checks() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE public.interventions_working w
     SET open_checks = (SELECT count(*) FROM public.qa_person_checks c WHERE c.record_id = w.record_id AND c.status = 'open')
   WHERE w.record_id IN (SELECT r FROM (VALUES (CASE WHEN TG_OP <> 'INSERT' THEN OLD.record_id END),
                                              (CASE WHEN TG_OP <> 'DELETE' THEN NEW.record_id END)) v(r) WHERE r IS NOT NULL);
  RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.recount_open_checks() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER qa_person_checks_recount AFTER INSERT OR UPDATE OF status, record_id OR DELETE ON public.qa_person_checks
  FOR EACH ROW EXECUTE FUNCTION public.recount_open_checks();
CREATE POLICY "Public read published" ON public.interventions_working FOR SELECT TO anon, authenticated USING (NOT removed);
GRANT SELECT (record_id, ukprn, intervention_name, activity_status, intervention_description, intervention_strategy,
              students_targeted_exact, target_demographics, lifecycle_stages, linked_target_ids,
              risks_to_equality_of_opportunity, page, qa_status, open_checks, removed, updated_at)
  ON public.interventions_working TO anon;
DROP VIEW public.site_interventions;
CREATE VIEW public.site_interventions WITH (security_invoker = true) AS
SELECT w.record_id, w.ukprn, w.intervention_name, nullif(w.activity_status,'') AS activity_status,
       w.intervention_description AS description, public.json_list(w.intervention_strategy) AS strategies,
       w.students_targeted_exact AS students_targeted, public.json_list(w.target_demographics) AS target_demographics,
       public.json_list(w.lifecycle_stages) AS lifecycle_stages, public.json_list(w.linked_target_ids) AS linked_target_ids,
       public.json_list(w.risks_to_equality_of_opportunity) AS risks,
       CASE WHEN w.page ~ '^\d+$' THEN w.page::integer END AS page, w.qa_status,
       w.open_checks > 0 AS awaiting_review, w.updated_at
FROM public.interventions_working w WHERE NOT w.removed;
GRANT SELECT ON public.site_interventions TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.json_list(text) TO anon, authenticated;

-- 8. (5 Nov) Removing a record closes its other open items ('closed' status); restoring it reopens them.
--    Applied as migration close_items_on_removed_records: adds 'closed' to the status check, adds the
--    close/reopen step to decide_check after the record-level update, and closed the 75 items then open
--    on removed records.
