# TASO APP Explorer: technical notes

Notes for anyone (or any AI coding assistant) changing the site. Read these first.

## What this is
The TASO APP Explorer lets users search and compare the targets and interventions in English higher education providers' Access and Participation Plans (APPs). APPs are an Office for Students (OfS) requirement for English providers only, so say "England" or "English providers", not "UK". The site supports collaboration and shared learning. It must never rank or judge providers.

## How it is built
- **Two pages, each a single file:** `index.html` (public) and `review/index.html` (TASO team). All HTML, CSS and JavaScript stay inline in each file. No build step, no frameworks, no external libraries; charts and the map are hand-drawn inline SVG.
- **Hosting:** GitHub Pages, from the `taso-he/APP_Explorer_External` repository. Everything in the repository is public.
- **Data:** read live from Supabase (project `qcxeehhogngdxqjiekjq`) using the publishable key in the page. Row-level security limits that key to reading `site_providers`, `site_targets` and `site_interventions`, and adding rows to `site_feedback` and `institutional_contacts_qa`.
- **Reviewers** sign in by emailed link; access is any email in `qa_reviewers` (checked by the `is_reviewer()` function).

## Rules
- Never put a secret key in any file. Only the publishable key belongs in the pages.
- Keep the provider's own wording. Coding and grouping sit alongside it.
- Match UKPRNs as trimmed text (`.toString().trim()`), never as numbers.
- On-page text: hyphens, not em dashes; sentence case headings.
- Never delete data rows: set `removed = true` with a `removed_reason`.
- Back up a table to the `archive` schema before any bulk change.

## Useful places in index.html
- `const PILOT = new Set([...])`: UKPRNs that see the institutional QA buttons.
- `GROUPS`: student group codes and labels. Must match the codes in `docs/interventions_qa_rules.md`.
- `RAP_REGIONS`: regional access partnership outlines for the map.
- `SUPABASE`: the project URL and publishable key.
