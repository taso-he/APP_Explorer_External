"""
Automated QA of the interventions extraction, using Claude.

For each provider in an extraction export, this script sends Claude the plan's
pages for one intervention strategy at a time, with that strategy's extracted
records and the QA rules, and asks for a verdict on every field. Python then
checks every quote Claude gives against the PDF; a correction whose quote can't
be found is marked Unsure. Results are written to CSV files and, if you ask,
uploaded to Supabase (tables qa_claude_field_reviews, qa_claude_record_checks
and qa_claude_runs).

Ways to run it (Windows, from the repository folder):

  1. Estimate the cost first (free: uses Anthropic's token counter, no review):
       python taso-handover\\scripts\\review_interventions_claude.py --export FILE --estimate
  2. Review one provider straight away:
       python taso-handover\\scripts\\review_interventions_claude.py --export FILE --ukprn 10000720
  3. Review every provider at half price with the Batch API (results within 24 hours, usually
     within an hour or two). Send the batch, then collect it later with the run ID it prints:
       python taso-handover\\scripts\\review_interventions_claude.py --export FILE --batch
       python taso-handover\\scripts\\review_interventions_claude.py --collect claude-20261102-101500 --upload

Run prepare_extraction.py on the export first, and review its _prepared.csv file.

Options:
  --export FILE     extraction export (CSV or XLSX); default: the 22 Oct 11:45 run
  --ukprn LIST      only these providers (comma-separated)
  --model NAME      default claude-opus-5-5
  --effort LEVEL    low | medium | high (default) | xhigh | max
  --dry-run         build every request and estimate tokens offline, with no API calls
  --batch           send every request as one Batch API job (half price) and stop
  --collect ID      fetch a finished batch's answers and save them like a normal run
  --upload          also upload results to Supabase
  --upload-only ID  upload a finished run's saved CSV files (e.g. claude-20261028-111825), no new review

Needs:  pip install pypdf openpyxl
(Claude is called with Python's built-in web tools, so nothing compiled is installed
for Windows Smart App Control to block.)
Keys (set as Windows environment variables, never in this file):
  ANTHROPIC_API_KEY                       for the review
  SUPABASE_URL, SUPABASE_SERVICE_KEY      only for --upload
"""

import argparse
import base64
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("A library is missing. Run: python -m pip install pypdf openpyxl")

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DOCS = HERE.parent / "docs"
PROMPT_VERSION = "claude-v5"

FIELDS = [
    "intervention_name", "intervention_description", "intervention_strategy", "students_targeted_exact",
    "target_demographics", "demographics_combined", "lifecycle_stages", "linked_target_ids",
    "linked_targets_text", "risks_to_equality_of_opportunity", "page",
]
LIST_FIELDS = {"intervention_strategy", "target_demographics", "lifecycle_stages", "linked_target_ids",
               "linked_targets_text", "risks_to_equality_of_opportunity"}
DEMOGRAPHIC_CODES = {
    "age", "disability", "ethnicity", "sex", "lgbtq", "region", "area_based", "fsm", "low_income", "first_in_family",
    "care_experienced", "estranged", "carer", "parents", "military", "gtrsb", "refugee_asylum",
    "child_in_need", "ex_prisoner", "religion", "commuter", "entry_route", "mode_of_study", "mental_health", "abcs", "all_students", "other",
}
LIFECYCLE_CODES = {"pre_entry_attainment", "access", "transition", "continuation", "completion",
                   "attainment", "progression", "whole_lifecycle"}
STATUSES = ["Correct", "Partly correct", "Incorrect", "Missing", "Unsure"]
ERROR_TYPES = ["", "missing value", "wrong value", "extra value (inferred, not in the plan)",
               "not copied exactly", "taken from the wrong place", "formatting only"]

# US dollars per million tokens: input, output, cache write (5-minute), cache read
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
}
# Rough planning figures for --dry-run (the --estimate option measures the real input)
TOKENS_PER_PDF_PAGE = 2500
OUTPUT_TOKENS_PER_RECORD = 700
THINKING_TOKENS_PER_REQUEST = 4000

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "missing_records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string"},
                    "evidence_quote": {"type": "string"},
                    "evidence_page": {"type": "integer"},
                },
                "required": ["activity", "evidence_quote", "evidence_page"],
                "additionalProperties": False,
            },
        },
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "string"},
                    "is_intervention": {"type": "string", "enum": ["Yes", "Not an intervention", "Duplicate", "Unsure"]},
                    "duplicate_of": {"type": "string"},
                    "record_reason": {"type": "string"},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string", "enum": FIELDS},
                                "status": {"type": "string", "enum": STATUSES},
                                "error_type": {"type": "string", "enum": ERROR_TYPES},
                                "corrected_value": {"type": "string"},
                                "evidence_quote": {"type": "string"},
                                "evidence_page": {"type": "integer"},
                            },
                            "required": ["field", "status", "error_type", "corrected_value",
                                         "evidence_quote", "evidence_page"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["record_id", "is_intervention", "duplicate_of", "record_reason", "fields"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["records", "missing_records"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You are checking records produced by an automated extraction of interventions from an English
higher education provider's Access and Participation Plan. For each record you are given, compare every
field with the plan pages provided and give a verdict, following the QA rules below exactly.

How to answer:
- Give one entry in "records" for every record_id you are given, and one entry in "fields" for each of
  the 11 fields of that record.
- status "Correct": corrected_value, evidence_quote and error_type are empty strings, evidence_page 0.
- Any other status: give the corrected value in the same format as the extracted value (JSON lists stay
  JSON lists, e.g. ["area_based"]; demographics_combined is True or False; page is a number), an
  evidence_quote of up to 30 words copied exactly from the plan pages, and evidence_page as the page
  number of the PLAN (not of the extract you were sent; the mapping is given with each request).
- Where the pages don't let you decide, use "Unsure" and say why in evidence_quote. The QA rules settle
  most questions of interpretation (related targets, combined groups, stages in the Outcomes column,
  vague group names, EORR risks): apply them rather than marking Unsure.
- If the value you would give is the same as the extracted value, the status is "Correct", even if you
  had to look hard to confirm it.
- Pages with the provider's objectives and targets are included where they can be found. Read them
  before deciding linked_target_ids, lifecycle_stages and students_targeted_exact.
- is_intervention: "Yes" for a row of a strategy table; "Not an intervention" for financial support or
  anything else the rules exclude; "Duplicate" (with duplicate_of) only if two records describe the
  same row of the same table; "Unsure" for narrative services outside the tables.
- Check linked_targets_text against the provider's targets list you are given.
- Where only the format is wrong (e.g. risks not written as "EORR Risk N – name"), use status
  "Partly correct" with error_type "formatting only", and give the value in the standard format.
- Judge only against the plan. Do not improve the provider's wording.
- A record listing several strategies is one activity repeated across those strategies' tables. Its
  risks are every listed strategy's risks, and its lifecycle stages and linked targets come from every
  listed strategy. Some of these may already have been added before your check; judge the value as it
  now stands.
- Codes can be reused for different activities (e.g. ISM6 for three different programmes in three
  strategies). Decide by the description, never by the code.
- missing_records: list any row of THIS strategy's table that has no record, giving its name as the plan
  writes it, a quote of up to 30 words and its plan page. A row counts as covered if any record for
  this provider (listed in the request, including records filed under other strategies) describes the
  same activity. Leave the list empty if every row is covered.

QA RULES
"""


# ---------- helpers ----------

def norm(text):
    """Lower case, one space, plain quotes and dashes, no bullets, encoding faults repaired."""
    t = str(text or "")
    t = t.replace("020", "’").replace(" 013 ", " – ")
    t = unicodedata.normalize("NFKC", t)
    t = t.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                   "–": "-", "—": "-", "•": " ", "": " ", "●": " "}))
    t = re.sub(r"(\w)- (\w)", r"\1-\2", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def read_export(path):
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        head = [str(h) for h in rows[0]]
        out = []
        for r in rows[1:]:
            d = {h: ("" if v is None else str(int(v)) if isinstance(v, float) and v == int(v) else str(v))
                 for h, v in zip(head, r)}
            if d.get("record_id"):
                out.append(d)
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("record_id")]


def load_targets():
    aims = defaultdict(dict)
    path = DATA / "targets.csv"
    if path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("current_plan", "Yes").strip() == "Yes":
                    aims[r["ukprn"].strip()][r["reference_number"].strip()] = r["aim"].strip()
    return aims


def sync_targets(row, aims):
    """Keep only target references in the provider's targets list, and set linked_targets_text from them.
    Returns a note of what changed ("" if nothing). Rows for providers with no targets are left alone."""
    known = aims.get(str(row.get("ukprn", "")).strip(), {})
    if not known:
        return ""
    try:
        ids = json.loads(row.get("linked_target_ids") or "[]")
    except json.JSONDecodeError:
        return ""
    if not isinstance(ids, list):
        return ""
    keep = [i for i in ids if str(i).strip() in known]
    text = json.dumps([known[str(i).strip()] for i in keep], ensure_ascii=False)
    notes = []
    if keep != ids:
        notes.append("target refs not in the targets list dropped: " + ", ".join(str(i) for i in ids if i not in keep))
        row["linked_target_ids"] = json.dumps(keep, ensure_ascii=False)
    if text != (row.get("linked_targets_text") or "") and not same_value(text, row.get("linked_targets_text")):
        notes.append("target text set from the targets list")
    row["linked_targets_text"] = text
    return "; ".join(notes)


def get_pdf(ukprn, source_file, pdf_dir):
    """The plan PDF, downloaded once from the OfS link in institutions.csv."""
    path = pdf_dir / f"{ukprn}.pdf"
    if path.exists() and path.stat().st_size > 0:
        return path
    url = ""
    with open(DATA / "institutions.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["ukprn"].strip() == ukprn:
                url = r.get("plan_url", "").strip()
    if not url:
        sys.exit(f"No plan link for UKPRN {ukprn}. Put the PDF in {pdf_dir} named {ukprn}.pdf")
    if source_file and urllib.request.unquote(url.rsplit("/", 1)[-1]) != source_file:
        print(f"  Note: the plan link ({url.rsplit('/', 1)[-1]}) differs from the export's source file "
              f"({source_file}). Put the right PDF in {pdf_dir} named {ukprn}.pdf if needed.")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        path.write_bytes(resp.read())
    return path


def strategy_number(label):
    m = re.match(r"\s*([\d.]+)", label or "")
    return m.group(1) if m else ""


def page_window(records, texts, strategy_label):
    """Plan pages to send for one strategy: its rows plus its introduction page."""
    pages = sorted({int(r["page"]) for r in records if str(r.get("page", "")).isdigit()})
    n = len(texts)
    if not pages:
        return list(range(1, min(n, 10) + 1))
    # Two pages after the last row: rows and their risk lines often run over
    first, last = max(1, pages[0] - 1), min(n, pages[-1] + 2)
    num = strategy_number(strategy_label)
    if num:
        pattern = re.compile(r"intervention\s+strateg(?:y|ies)\s*" + re.escape(num) + r"\b", re.I)
        for p in range(pages[0], max(0, pages[0] - 8), -1):
            if pattern.search(texts[p - 1] or ""):
                first = min(first, p)
                break
    return list(range(first, last + 1))


def objectives_pages(texts, aims, limit=3):
    """Pages that set out the provider's objectives and targets, so the reviewer can check target links
    (a fifth of the first run's Unsure verdicts were for want of them). Scores each page by how many of
    the provider's target references (e.g. PTS_1) and numbered objectives ("Objective 3", "Obj 3",
    "O4.1") it names. The annex targets tables are left out: the targets list is sent as text anyway."""
    refs = [r for r in aims if r]
    pats = [re.compile(re.escape(r).replace("_", r"[_\s-]?") + r"\b", re.I) for r in refs]
    objective = re.compile(r"\b(?:objective|obj|o)\s?(\d+(?:\.\d+)?[a-z]?)\b", re.I)
    main = max(1, int(len(texts) * 0.75))  # annexes are at the back
    scored = []
    for p, t in enumerate(texts[:main], start=1):
        t = t or ""
        if "contents" in t[:300].lower():
            continue
        n = sum(1 for pat in pats if pat.search(t)) + len({m.group(1) for m in objective.finditer(t)})
        if n >= 3 and re.search(r"objective|target", t, re.I):
            scored.append((-n, p))
    return sorted(p for _, p in sorted(scored)[:limit])


def image_page(texts, page):
    """True when the PDF page has almost no text, i.e. the table on it is an image."""
    return all(len((texts[p - 1] or "").strip()) < 80 for p in (page,) if 1 <= p <= len(texts))


def strategy_intro_pages(texts, label):
    """A strategy's section (its introduction and activity table), so a merged record can be checked against it."""
    num = strategy_number(label)
    if not num:
        return []
    pattern = re.compile(r"intervention\s+strateg(?:y|ies)\s*" + re.escape(num) + r"\b", re.I)
    any_strategy = re.compile(r"intervention\s+strateg(?:y|ies)\s*([\d.]+)", re.I)
    for p, t in enumerate(texts, start=1):
        if pattern.search(t or "") and "contents" not in (t or "")[:300].lower():
            # The strategy's whole section: up to the next strategy's heading, at most 8 pages
            pages = [p]
            for q in range(p + 1, min(p + 8, len(texts) + 1)):
                if any(m.group(1).rstrip(".") != num.rstrip(".") for m in any_strategy.finditer(texts[q - 1] or "")):
                    pages.append(q)
                    break
                pages.append(q)
            return pages
    return []


def describe_pages(pages):
    """'attachment pages 1-5 are plan pages 6-10; 6-7 are plan pages 20-21'"""
    runs, start = [], 0
    for i in range(1, len(pages) + 1):
        if i == len(pages) or pages[i] != pages[i - 1] + 1:
            runs.append((start + 1, i, pages[start], pages[i - 1]))
            start = i
    return "; ".join(f"attachment pages {a}-{b} are plan pages {c}-{d}" if a != b
                     else f"attachment page {a} is plan page {c}" for a, b, c, d in runs)


def extract_pages(pdf_path, page_numbers):
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for p in page_numbers:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def build_requests(rows, aims, pdf_dir, rules):
    """One request per provider and strategy (records outside the tables go one at a time)."""
    by_provider = defaultdict(list)
    for r in rows:
        by_provider[r["ukprn"].strip()].append(r)
    requests = []
    for ukprn, recs in by_provider.items():
        provider = recs[0]["provider"]
        pdf_path = get_pdf(ukprn, recs[0].get("source_file", ""), pdf_dir)
        texts = [pg.extract_text() or "" for pg in PdfReader(str(pdf_path)).pages]
        groups = defaultdict(list)
        for r in recs:
            try:
                label = (json.loads(r.get("intervention_strategy") or "[]") or ["(none)"])[0]
            except json.JSONDecodeError:
                label = r.get("intervention_strategy") or "(none)"
            if label == "Outside strategy tables" or label == "(none)":
                groups[(label, r["record_id"])].append(r)
            else:
                groups[(label, "")].append(r)
        target_list = "\n".join(f"{ref}: {aim}" for ref, aim in sorted(aims.get(ukprn, {}).items()))
        all_records = "\n".join(f"- {r.get('intervention_name', '')} | {r.get('intervention_strategy', '')}" for r in recs)
        for (label, _), group in groups.items():
            pages = set(page_window(group, texts, label))
            # The provider's objectives and targets, wherever they are in the plan
            pages.update(objectives_pages(texts, aims.get(ukprn, {})))
            # A record may list several strategies: add each one's introduction for its targets and risks
            for r in group:
                try:
                    for other in json.loads(r.get("intervention_strategy") or "[]")[1:]:
                        pages.update(strategy_intro_pages(texts, other))
                except json.JSONDecodeError:
                    pass
            pages = sorted(pages)
            records = [{"record_id": r["record_id"], **{f: r.get(f, "") for f in FIELDS}} for r in group]
            text = (
                f"Provider: {provider} (UKPRN {ukprn})\n"
                f"Strategy: {label}\n"
                f"The PDF attached holds these plan pages: {describe_pages(pages)}. "
                f"Give evidence_page as the plan page number.\n\n"
                f"The provider's current-plan targets (reference: aim):\n{target_list or '(none found)'}\n\n"
                f"Every record extracted for this provider (name | strategies), for missing_records:\n{all_records}\n\n"
                f"Records to check:\n{json.dumps(records, ensure_ascii=False, indent=1)}"
            )
            requests.append({
                "ukprn": ukprn, "provider": provider, "strategy": label, "pages": pages,
                "records": group, "texts": texts,
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                    "data": extract_pages(pdf_path, pages)}},
                    {"type": "text", "text": text},
                ],
            })
    return requests


def system_blocks(rules):
    # Stable text first, cached, so every request after the first reads it at the cache price
    return [{"type": "text", "text": INSTRUCTIONS + rules, "cache_control": {"type": "ephemeral"}}]


def check_field(entry, texts):
    """Python's check on one verdict: quote on the stated page (or next to it), codes on the lists."""
    status = entry["status"]
    if status in ("Correct", "Unsure"):
        return status, None
    problems = []
    quote, page = norm(entry.get("evidence_quote")), entry.get("evidence_page") or 0
    found = False
    if quote and 1 <= page <= len(texts):
        for p in (page, page - 1, page + 1):
            # Compared without spaces, because PDF text often splits words ("Pe rsonal")
            if 1 <= p <= len(texts) and quote.replace(" ", "") in norm(texts[p - 1]).replace(" ", ""):
                found = True
                break
    if not found and 1 <= page <= len(texts) and image_page(texts, page):
        # The page is an image, so Python can't read the quote; the correction goes to a spot check instead
        found = "image"
    elif not found:
        problems.append("quote not found on that page")
    field, value = entry["field"], entry.get("corrected_value", "")
    if field in LIST_FIELDS and value:
        try:
            items = json.loads(value)
            if not isinstance(items, list):
                problems.append("corrected value is not a list")
            elif field == "target_demographics" and not set(items) <= DEMOGRAPHIC_CODES:
                problems.append("demographic code not on the list")
            elif field == "lifecycle_stages" and not set(items) <= LIFECYCLE_CODES:
                problems.append("lifecycle code not on the list")
        except json.JSONDecodeError:
            problems.append("corrected value is not valid JSON")
    return ("Unsure" if problems else status), found


def same_value(a, b):
    """The extracted and corrected values are the same (JSON lists compared as sets, text normalised)."""
    a, b = str(a or "").strip(), str(b or "").strip()
    if not b:
        return False
    if a.startswith("[") and b.startswith("["):
        try:
            return sorted(map(str, json.loads(a))) == sorted(map(str, json.loads(b)))
        except json.JSONDecodeError:
            pass
    return norm(a) == norm(b)


def cost(usage_totals, model):
    p_in, p_out, p_write, p_read = PRICES.get(model, PRICES["claude-opus-5-5"])
    u = usage_totals
    return (u["input"] * p_in + u["output"] * p_out + u["cache_write"] * p_write + u["cache_read"] * p_read) / 1e6


def supabase_settings():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", key)) if not v]
        sys.exit(f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set in this Command Prompt. Save with setx (see the guide), "
                 "then close this window and open a new one. Nothing has been reviewed or charged.")
    return url, key


def upload_saved_run(out_dir, run_id):
    """Upload the three CSV files a run saved, putting numbers and true/false back into their types."""
    def load(name):
        path = out_dir / f"{run_id}_{name}.csv"
        if not path.exists():
            sys.exit(f"Can't find {path}")
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    run = load("run")
    for r in run:
        for k in ("records", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens"):
            r[k] = int(r[k]) if r[k] else None
        r["cost_usd"] = float(r["cost_usd"]) if r["cost_usd"] else None
    fields = load("field_reviews")
    for r in fields:
        r["evidence_page"] = int(r["evidence_page"]) if r["evidence_page"] else None
        r["quote_verified"] = {"True": True, "False": False}.get(r["quote_verified"])
    records = load("record_checks")
    upload("qa_claude_runs", run)
    upload("qa_claude_field_reviews", fields)
    upload("qa_claude_record_checks", records)
    print(f"Uploaded run {run_id}: {len(fields)} field verdicts and {len(records)} record checks.")


def upload(table, rows):
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Set SUPABASE_URL and SUPABASE_SERVICE_KEY to upload (see the guide).")
    headers = {"apikey": key, "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    if key.startswith("eyJ"):  # an older service_role key also goes in the Authorization header
        headers["Authorization"] = f"Bearer {key}"
    if table == "qa_claude_field_reviews":
        # quote_verified is true/false in Supabase. "image" (a quote on an image page, which Python can't read)
        # stays in the saved CSV for apply_review_corrections.py, and goes to Supabase as empty: not checked.
        rows = [{**r, "quote_verified": {True: True, False: False, "True": True, "False": False}.get(r.get("quote_verified"))}
                for r in rows]
    for i in range(0, len(rows), 200):
        req = urllib.request.Request(
            f"{url.rstrip('/')}/rest/v1/{table}", data=json.dumps(rows[i:i + 200]).encode("utf-8"), method="POST",
            headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60):
                pass
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            hint = (" The table may be missing write permission for the secret key: run the GRANT lines at the end of "
                    "6_claude_review_tables.sql." if e.code in (401, 403) else "")
            sys.exit(f"Supabase refused the upload to {table} (error {e.code}): {detail}{hint}")


# ---------- calling Claude ----------

API_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1"


def api_post(path, body, stream=False):
    """POST to the Claude API. Retries a few times if it's busy or rate limited."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY isn't set. Save it with setx (see the guide) and open a new Command Prompt.")
    headers = {"x-api-key": key, "anthropic-version": "2026-10-21", "content-type": "application/json"}
    if "fallbacks" in body:
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
    data = json.dumps(body).encode("utf-8")
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(API_URL + path, data=data, headers=headers,
                                                                 method="POST"), timeout=900)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                wait = 60 * (attempt + 1)
                print(f"  The API is busy or rate limited ({e.code}): waiting {wait} seconds and trying again.")
                time.sleep(wait)
                continue
            if e.code == 401:
                sys.exit("The API key was refused. Check ANTHROPIC_API_KEY (see the guide).")
            sys.exit(f"The Claude API returned an error {e.code}: {detail}")


def count_tokens(model, content, system=None):
    body = {"model": model, "messages": [{"role": "user", "content": content}]}
    if system:
        body["system"] = system
    with api_post("/messages/count_tokens", body) as resp:
        return json.loads(resp.read())["input_tokens"]


def review(model, effort, system, content):
    """One streamed request; returns the answer text, stop reason, model and token usage."""
    body = {**request_body(model, effort, system, content), "stream": True, "fallbacks": "default"}
    result = {"text": "", "stop_reason": None, "model": model,
              "usage": {"input_tokens": 0, "output_tokens": 0,
                        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
    text_blocks = set()
    with api_post("/messages", body, stream=True) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            kind = event.get("type")
            if kind == "message_start":
                msg = event["message"]
                result["model"] = msg.get("model") or model
                for k, v in (msg.get("usage") or {}).items():
                    if k in result["usage"] and isinstance(v, int):
                        result["usage"][k] = v
            elif kind == "content_block_start":
                if event["content_block"].get("type") == "text":
                    text_blocks.add(event["index"])
                    result["text"] = ""  # keep only the last text block (after any fallback)
            elif kind == "content_block_delta":
                delta = event["delta"]
                if delta.get("type") == "text_delta" and event["index"] in text_blocks:
                    result["text"] += delta["text"]
            elif kind == "message_delta":
                result["stop_reason"] = event["delta"].get("stop_reason") or result["stop_reason"]
                for k, v in (event.get("usage") or {}).items():
                    if k in result["usage"] and isinstance(v, int):
                        result["usage"][k] = v
            elif kind == "error":
                print(f"  The API reported an error mid-answer: {event.get('error')}")
                result["stop_reason"] = "error"
    return result


def api_get(url):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY isn't set. Save it with setx (see the guide) and open a new Command Prompt.")
    req = urllib.request.Request(url, headers={"x-api-key": key, "anthropic-version": "2026-10-21"})
    try:
        return urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        sys.exit(f"The Claude API returned an error {e.code}: {e.read().decode('utf-8', 'replace')}")


def request_body(model, effort, system, content):
    return {
        "model": model, "max_tokens": 64000, "system": system,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    }


def submit_batches(requests, model, effort, system):
    """Send the requests as Batch API jobs, split so each job stays well under the 256 MB limit."""
    ids, chunk, size = [], [], 0
    def send():
        with api_post("/messages/batches", {"requests": chunk}) as resp:
            ids.append(json.loads(resp.read())["id"])
    for i, req in enumerate(requests):
        item = {"custom_id": f"req-{i:04d}", "params": request_body(model, effort, system, req["content"])}
        n = len(json.dumps(item))
        if chunk and size + n > 150_000_000:
            send()
            chunk, size = [], 0
        chunk.append(item)
        size += n
    send()
    return ids


def batch_message(result):
    """A batch answer in the same shape as review() returns."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    if result.get("type") != "succeeded":
        print(f"  {result.get('type')}: {json.dumps(result.get('error', ''))[:200]}")
        return {"text": "", "stop_reason": "error", "model": "", "usage": usage}
    msg = result["message"]
    for k, v in (msg.get("usage") or {}).items():
        if k in usage and isinstance(v, int):
            usage[k] = v
    texts = [b["text"] for b in msg.get("content", []) if b.get("type") == "text"]
    return {"text": texts[-1] if texts else "", "stop_reason": msg.get("stop_reason"),
            "model": msg.get("model", ""), "usage": usage}


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(DATA / "extracted_interventions_2026-10-22_1145.csv"))
    ap.add_argument("--ukprn")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--pdfs", default=str(HERE / "plan_pdfs"))
    ap.add_argument("--out", default=str(HERE / "claude_review_results"))
    ap.add_argument("--estimate", action="store_true", help="count tokens with the API (free), no review")
    ap.add_argument("--dry-run", action="store_true", help="offline estimate, no API calls at all")
    ap.add_argument("--batch", action="store_true", help="send the review as Batch API jobs (half price) and stop")
    ap.add_argument("--collect", metavar="RUN_ID", help="fetch the answers to a batch sent with --batch")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--upload-only", metavar="RUN_ID",
                    help="upload a finished run's saved CSV files to Supabase, with no new review")
    args = ap.parse_args()

    if args.upload or args.upload_only:
        supabase_settings()
    if args.upload_only:
        upload_saved_run(Path(args.out), args.upload_only)
        return
    if args.collect:
        collect(args)
        return

    rows = read_export(args.export)
    if args.ukprn:
        keep = {u.strip() for u in args.ukprn.split(",")}
        rows = [r for r in rows if r["ukprn"].strip() in keep]
    if not rows:
        sys.exit("No records found for those providers in the export.")
    pdf_dir, out_dir = Path(args.pdfs), Path(args.out)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    rules = (DOCS / "interventions_qa_rules.md").read_text(encoding="utf-8")
    extraction_run = rows[0].get("extraction_run_id") or Path(args.export).stem

    print(f"Preparing requests for {len({r['ukprn'] for r in rows})} providers, {len(rows)} records...")
    requests = build_requests(rows, load_targets(), pdf_dir, rules)
    pages = sum(len(r["pages"]) for r in requests)
    print(f"{len(requests)} requests, {pages} PDF pages in total")

    p_in, p_out, p_write, p_read = PRICES.get(args.model, PRICES["claude-opus-5-5"])
    if args.dry_run or args.estimate:
        if args.dry_run:
            rules_tokens = len(INSTRUCTIONS + rules) // 4
            input_tokens = sum(len(r["pages"]) * TOKENS_PER_PDF_PAGE + len(r["content"][1]["text"]) // 4
                               for r in requests)
            source = "offline guess (about 2,500 tokens per PDF page)"
        else:
            rules_tokens = count_tokens(args.model, INSTRUCTIONS + rules)
            input_tokens = 0
            for r in requests:
                input_tokens += count_tokens(args.model, r["content"])
            source = "Anthropic token counter"
        output_tokens = len(rows) * OUTPUT_TOKENS_PER_RECORD + len(requests) * THINKING_TOKENS_PER_REQUEST
        low = (input_tokens * p_in + rules_tokens * (p_write + (len(requests) - 1) * p_read)
               + output_tokens * 0.6 * p_out) / 1e6
        high = (input_tokens * p_in + rules_tokens * (p_write + (len(requests) - 1) * p_read)
                + output_tokens * 1.6 * p_out) / 1e6
        print(f"\nInput tokens ({source}): {input_tokens:,} plus {rules_tokens:,} for the rules (cached)")
        print(f"Output tokens (estimate, including thinking): about {output_tokens:,}")
        print(f"Estimated cost with {args.model}: ${low:.2f} to ${high:.2f} "
              f"(about ${(low + high) / 2 / len({r['ukprn'] for r in rows}):.2f} per provider); "
              f"with --batch, half that: ${low / 2:.2f} to ${high / 2:.2f}")
        return

    review_run_id = datetime.now(timezone.utc).strftime("claude-%Y%m%d-%H%M%S")
    started = datetime.now(timezone.utc).isoformat()

    if args.batch:
        batch_ids = submit_batches(requests, args.model, args.effort, system_blocks(rules))
        manifest = {
            "review_run_id": review_run_id, "started_at": started, "export": str(Path(args.export).resolve()),
            "pdfs": str(pdf_dir.resolve()), "model": args.model, "effort": args.effort, "batch_ids": batch_ids,
            "requests": [{"custom_id": f"req-{i:04d}", "ukprn": r["ukprn"], "provider": r["provider"],
                          "strategy": r["strategy"], "pages": r["pages"],
                          "record_ids": [x["record_id"] for x in r["records"]]} for i, r in enumerate(requests)],
        }
        (out_dir / f"{review_run_id}_batch.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(f"\nSent {len(requests)} requests as {len(batch_ids)} batch job(s): {', '.join(batch_ids)}")
        print(f"Run ID {review_run_id}. Check back in an hour or two (at most 24 hours) with:")
        print(f"  python taso-handover\\scripts\\review_interventions_claude.py --collect {review_run_id} --upload")
        return

    messages = []
    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    for i, req in enumerate(requests, start=1):
        print(f"[{i}/{len(requests)}] {req['provider']}: {req['strategy'][:60]} "
              f"({len(req['records'])} records, pages {req['pages'][0]}-{req['pages'][-1]})", flush=True)
        message = review(args.model, args.effort, system_blocks(rules), req["content"])
        messages.append(message)
        add_usage(totals, message["usage"])
        print(f"  tokens in {message['usage']['input_tokens']:,}, out {message['usage']['output_tokens']:,}; "
              f"running cost ${cost(totals, args.model):.2f}")
    finish(requests, messages, review_run_id, started, args.model, args.effort, rows, extraction_run, out_dir,
           args.upload, discount=1.0)


def add_usage(totals, u):
    totals["input"] += u["input_tokens"]
    totals["output"] += u["output_tokens"]
    totals["cache_write"] += u["cache_creation_input_tokens"]
    totals["cache_read"] += u["cache_read_input_tokens"]


def collect(args):
    """Fetch a finished batch's answers, then save and upload them like a normal run."""
    out_dir = Path(args.out)
    path = out_dir / f"{args.collect}_batch.json"
    if not path.exists():
        sys.exit(f"Can't find {path}. Use the run ID that --batch printed.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    results, waiting = {}, False
    for batch_id in manifest["batch_ids"]:
        with api_get(f"{API_URL}/messages/batches/{batch_id}") as resp:
            batch = json.loads(resp.read())
        counts = batch.get("request_counts", {})
        print(f"Batch {batch_id}: {batch['processing_status']} "
              f"({', '.join(f'{k} {v}' for k, v in counts.items())})")
        if batch["processing_status"] != "ended":
            waiting = True
            continue
        with api_get(batch["results_url"]) as resp:
            for line in resp:
                if line.strip():
                    item = json.loads(line)
                    results[item["custom_id"]] = item["result"]
    if waiting:
        sys.exit("Not finished yet. Nothing has been saved: try --collect again later.")

    rows = read_export(manifest["export"])
    by_id = {r["record_id"]: r for r in rows}
    pdf_dir = Path(manifest["pdfs"])
    texts_by_provider, requests, messages = {}, [], []
    for meta in manifest["requests"]:
        uk = meta["ukprn"]
        if uk not in texts_by_provider:
            texts_by_provider[uk] = [pg.extract_text() or "" for pg in PdfReader(str(pdf_dir / f"{uk}.pdf")).pages]
        requests.append({**meta, "records": [by_id[i] for i in meta["record_ids"] if i in by_id],
                         "texts": texts_by_provider[uk]})
        messages.append(batch_message(results.get(meta["custom_id"], {"type": "missing"})))
    reviewed = {i for m in manifest["requests"] for i in m["record_ids"]}
    rows = [r for r in rows if r["record_id"] in reviewed]
    extraction_run = rows[0].get("extraction_run_id") or Path(manifest["export"]).stem
    finish(requests, messages, manifest["review_run_id"], manifest["started_at"], manifest["model"],
           manifest["effort"], rows, extraction_run, out_dir, args.upload, discount=0.5)


def finish(requests, messages, review_run_id, started, model, effort, rows, extraction_run, out_dir, do_upload,
           discount):
    """Check every verdict, save the CSV files and, if asked, upload them."""
    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    field_rows, record_rows, missing_rows = [], [], []
    for req, message in zip(requests, messages):
        add_usage(totals, message["usage"])
        answer = {"records": []}
        if message["stop_reason"] in ("refusal", "max_tokens", "error"):
            print(f"  {req['provider']}, {req['strategy'][:50]}: stopped early ({message['stop_reason']}), "
                  "so these records are marked Unsure.")
        else:
            try:
                answer = json.loads(message["text"])
            except json.JSONDecodeError:
                print(f"  {req['provider']}, {req['strategy'][:50]}: the answer wasn't valid JSON, "
                      "so these records are marked Unsure.")

        served = message["model"] or model  # differs if Anthropic passed a declined request to a fallback model
        by_id = {rec["record_id"]: rec for rec in answer.get("records", [])}
        now = datetime.now(timezone.utc).isoformat()
        for m in answer.get("missing_records", []):
            quote = norm(m.get("evidence_quote")).replace(" ", "")
            page = m.get("evidence_page") or 0
            found = bool(quote) and any(1 <= p <= len(req["texts"]) and quote in norm(req["texts"][p - 1]).replace(" ", "")
                                        for p in (page, page - 1, page + 1))
            missing_rows.append({"review_run_id": review_run_id, "provider": req["provider"], "ukprn": req["ukprn"],
                                 "strategy": req["strategy"], "activity": m.get("activity", ""),
                                 "evidence_quote": m.get("evidence_quote", ""), "evidence_page": page or None,
                                 "quote_verified": found})
        for r in req["records"]:
            got = by_id.get(r["record_id"])
            record_rows.append({
                "review_run_id": review_run_id, "record_id": r["record_id"], "provider": r["provider"],
                "status": got["is_intervention"] if got else "Unsure",
                "duplicate_of": got["duplicate_of"] if got else "",
                "reason": got["record_reason"] if got else "No answer from the model",
                "model": served, "prompt_version": PROMPT_VERSION, "reviewed_at": now})
            entries = {e["field"]: e for e in (got["fields"] if got else [])}
            for f in FIELDS:
                e = entries.get(f, {"field": f, "status": "Unsure", "error_type": "", "corrected_value": "",
                                    "evidence_quote": "No verdict returned", "evidence_page": 0})
                status, verified = check_field(e, req["texts"])
                if status != "Correct" and same_value(r.get(f, ""), e.get("corrected_value", "")):
                    # Claude's "correction" is the value already there: nothing for anyone to decide
                    status, verified = "Correct", None
                field_rows.append({
                    "review_run_id": review_run_id, "record_id": r["record_id"], "provider": r["provider"],
                    "ukprn": r["ukprn"].strip(), "field": f, "extracted_value": r.get(f, ""),
                    "status": status, "error_type": e["error_type"] if status != "Correct" else "",
                    "corrected_value": e["corrected_value"] if status != "Correct" else "",
                    "evidence_quote": e["evidence_quote"], "evidence_page": e["evidence_page"] or None,
                    "quote_verified": verified, "model": served, "prompt_version": PROMPT_VERSION,
                    "reviewed_at": now})

    run_cost = cost(totals, model) * discount
    run_row = {"review_run_id": review_run_id, "model": model, "effort": effort,
               "prompt_version": PROMPT_VERSION, "extraction_run": extraction_run,
               "providers": ", ".join(sorted({r["provider"] for r in rows})), "records": len(rows),
               "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
               "input_tokens": totals["input"], "output_tokens": totals["output"],
               "cache_write_tokens": totals["cache_write"], "cache_read_tokens": totals["cache_read"],
               "cost_usd": round(run_cost, 4)}

    missing_fields = ["review_run_id", "provider", "ukprn", "strategy", "activity", "evidence_quote",
                      "evidence_page", "quote_verified"]
    for name, data, cols in (("field_reviews", field_rows, None), ("record_checks", record_rows, None),
                             ("run", [run_row], None), ("missing_records", missing_rows, missing_fields)):
        with open(out_dir / f"{review_run_id}_{name}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols or list(data[0].keys()))
            w.writeheader()
            w.writerows(data)

    statuses = defaultdict(int)
    for fr in field_rows:
        statuses[fr["status"]] += 1
    print(f"\nRun {review_run_id}: {len(field_rows)} field verdicts " +
          ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())))
    print(f"Table rows Claude thinks have no record: {len(missing_rows)} (see {review_run_id}_missing_records.csv)")
    print(f"Tokens: input {totals['input']:,}, output {totals['output']:,}, cache read {totals['cache_read']:,}, "
          f"cache write {totals['cache_write']:,}. Cost: ${run_cost:.2f}" + (" (batch price)" if discount < 1 else ""))
    print(f"Results saved in {out_dir}")

    if do_upload:
        upload("qa_claude_runs", [run_row])
        upload("qa_claude_field_reviews", field_rows)
        upload("qa_claude_record_checks", record_rows)
        print("Uploaded to Supabase.")

if __name__ == "__main__":
    main()
