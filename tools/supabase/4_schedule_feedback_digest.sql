-- Run the weekly feedback email every Monday morning.
-- Run once in the Supabase SQL Editor, after the weekly-feedback-digest function is deployed
-- and its secrets are set. Replace PASTE-THE-SAME-DIGEST-SECRET-HERE with the DIGEST_SECRET value.

CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- Keep the shared secret in Supabase Vault rather than in the schedule itself
SELECT vault.create_secret('PASTE-THE-SAME-DIGEST-SECRET-HERE', 'feedback_digest_secret');

-- 07:41 UTC every Monday (08:41 in British Summer Time)
SELECT cron.schedule(
  'weekly-feedback-digest',
  '41 7 * * 1',
  $$
  SELECT net.http_post(
    url := 'https://qcxeehhogngdxqjiekjq.supabase.co/functions/v1/weekly-feedback-digest',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-digest-secret', (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'feedback_digest_secret')
    ),
    body := '{}'::jsonb
  );
  $$
);

-- To check it ran:  SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 5;
-- To stop it:       SELECT cron.unschedule('weekly-feedback-digest');
