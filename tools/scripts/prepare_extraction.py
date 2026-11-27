"""
Tidy an interventions extraction before the Claude review. No AI, no cost.

Three fixes and checks for patterns the extraction model gets wrong:

  1. Page numbers   finds each activity in the plan's PDF text and corrects the page
                    (the same check as find_intervention_pages.py).
  2. Merged risks   a record listed under several strategies should take the risks
                    of every one of them. Adds any risks the model left out, using
                    the risks it recorded for each strategy in strategies_found.
  3. Reused codes   flags activity codes used for different activities in different
                    strategies (e.g. ISM6 for three different programmes) where there
                    are fewer records than activities. These need checking by hand.
  4. Targets        drops target references that aren't in the provider's targets list
                    and sets linked_targets_text from the list (data\\targets.csv), so the
                    text always matches the references.

It can read the extraction straight from Supabase (--from-supabase): it takes every
provider's most recent extraction run from the extracted_interventions table and saves
it as extractions\\extraction_latest_<date>.csv first.

Writes, next to the export:
  <export>_prepared.csv   the export with pages and risks corrected, plus a
                          prep_notes column saying what changed
  <export>_prep_report.csv  one row per change or flag, for checking

Then run the Claude review on the _prepared.csv file.

Usage (Windows, from the repository folder):
  python taso-handover\\scripts\\prepare_extraction.py --from-supabase
  python taso-handover\\scripts\\prepare_extraction.py "C:\\path\\to\\export.csv"
Options:
  --from-supabase read the latest run per provider from Supabase (needs SUPABASE_URL and
                  SUPABASE_SERVICE_KEY, as for the Claude review's --upload)
  --ukprn LIST    with --from-supabase, only these providers (comma-separated)
  --include-loaded  with --from-supabase, also take providers already loaded for review
                  (by default they're left out, so only new plans are prepared)
  --pdfs FOLDER   plan PDFs named by UKPRN (default: taso-handover\\scripts\\plan_pdfs;
                  missing plans are downloaded from the OfS link in institutions.csv)

Needs: pip install pypdf
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from find_intervention_pages import check_page, read_pdf_pages  # noqa: E402
from review_interventions_claude import get_pdf, load_targets, sync_targets  # noqa: E402

CODE = re.compile(r"^\s*([A-Z]{2,5}\d{1,3})\b")


def json_list(v):
    try:
        x = json.loads(v or "[]")
        return x if isinstance(x, list) else []
    except json.JSONDecodeError:
        return re.findall(r'"([^"]+)"', v or "")


def strategy_number(label):
    m = re.match(r"\s*([\d.]+)", str(label or ""))
    return m.group(1).rstrip(".") if m else ""


def risk_number(risk):
    m = re.search(r"Risk\s*(\d+)", risk or "")
    return int(m.group(1)) if m else 99


def squash(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def fetch_from_supabase(ukprns=None, include_loaded=False):
    """Every provider's most recent extraction run, saved as a CSV in the same layout as Mikayla's export."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY need to be set (see the guide), then open a new Command Prompt.")
    headers = {"apikey": key}
    if key.startswith("eyJ"):  # an older service_role key also goes in the Authorization header
        headers["Authorization"] = f"Bearer {key}"

    def get(query, table="extracted_interventions"):
        out, offset = [], 0
        while True:
            req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/{table}?{query}"
                                         f"&limit=1000&offset={offset}", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    page = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                sys.exit(f"Supabase refused the request (error {e.code}): {e.read().decode('utf-8', 'replace')}")
            out += page
            if len(page) < 1000:
                return out
            offset += 1000

    # Find each provider's latest run, then fetch only those runs in full
    latest = {}
    for r in get("select=ukprn,extraction_run_id,extracted_at&order=extracted_at"):
        latest[str(r["ukprn"]).strip()] = r["extraction_run_id"]
    if ukprns:
        latest = {u: run for u, run in latest.items() if u in ukprns}
    elif not include_loaded:
        # Providers already loaded for review (interventions_working) have been through the checks:
        # leave them out, so a new run only covers plans that haven't been checked yet
        loaded = {str(r["ukprn"]).strip() for r in get("select=ukprn", "interventions_working")}
        skipped = sorted(u for u in latest if u in loaded)
        latest = {u: run for u, run in latest.items() if u not in loaded}
        if skipped:
            print(f"Left out {len(skipped)} providers already loaded for review (use --include-loaded to keep them).")
    if not latest:
        sys.exit("No extracted interventions found in Supabase for those providers.")
    rows = []
    for run in sorted(set(latest.values())):
        rows += [r for r in get(f"select=*&extraction_run_id=eq.{urllib.parse.quote(run)}&order=record_id")
                 if latest.get(str(r["ukprn"]).strip()) == run]

    out_dir = HERE / "extractions"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"extraction_latest_{date.today().isoformat()}.csv"
    fields = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if v is None else str(v) if isinstance(v, bool) else v for k, v in r.items()})
    print(f"Read {len(rows)} records for {len(latest)} providers from Supabase (latest run for each). Saved {path.name}.")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", nargs="?", help="an extraction export (CSV); leave out with --from-supabase")
    ap.add_argument("--from-supabase", action="store_true")
    ap.add_argument("--ukprn")
    ap.add_argument("--include-loaded", action="store_true",
                    help="with --from-supabase, also take providers already loaded for review")
    ap.add_argument("--pdfs", default=str(HERE / "plan_pdfs"))
    args = ap.parse_args()

    if args.from_supabase:
        src = fetch_from_supabase({u.strip() for u in args.ukprn.split(",")} if args.ukprn else None,
                                  args.include_loaded)
    elif args.export:
        src = Path(args.export)
    else:
        sys.exit("Give an export file, or use --from-supabase.")
    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = [r for r in reader if r.get("record_id")]
    if "prep_notes" not in fields:
        fields.append("prep_notes")
    pdf_dir = Path(args.pdfs)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    report = []
    aims = load_targets()
    by_provider = defaultdict(list)
    for r in rows:
        by_provider[r["ukprn"].strip()].append(r)

    for ukprn, recs in by_provider.items():
        provider = recs[0]["provider"]
        notes = defaultdict(list)

        # 1. Pages
        try:
            pages = read_pdf_pages(get_pdf(ukprn, recs[0].get("source_file", ""), pdf_dir))
        except SystemExit as e:
            pages = None
            report.append({"provider": provider, "ukprn": ukprn, "record_id": "", "intervention": "",
                           "check": "page", "change": f"Not checked: {e}"})
        if pages:
            for r in recs:
                page, source = check_page(pages, r.get("intervention_name"), r.get("intervention_description"), r.get("page"))
                if source == "model":
                    report.append({"provider": provider, "ukprn": ukprn, "record_id": r["record_id"],
                                   "intervention": r["intervention_name"], "check": "page",
                                   "change": f"Name and description not found near page {r.get('page')}: check by hand"})
                elif str(page) != str(r.get("page", "")).strip():
                    notes[r["record_id"]].append(f"page {r.get('page')} -> {page}")
                    report.append({"provider": provider, "ukprn": ukprn, "record_id": r["record_id"],
                                   "intervention": r["intervention_name"], "check": "page",
                                   "change": f"Page {r.get('page')} changed to {page} (found by its {source})"})
                    r["page"] = str(page)

        # The model's map of the plan: each strategy's risks and activities
        strategies = {}
        for r in recs:
            for s in json_list(r.get("strategies_found")):
                if isinstance(s, dict) and s.get("number"):
                    strategies[str(s["number"]).rstrip(".")] = s
            if strategies:
                break

        # 2. Merged risks
        for r in recs:
            listed = [strategy_number(x) for x in json_list(r.get("intervention_strategy"))]
            if len(listed) < 2:
                continue
            risks = json_list(r.get("risks_to_equality_of_opportunity"))
            have = {risk_number(x) for x in risks}
            added = []
            for n in listed:
                for risk in (strategies.get(n) or {}).get("risks_to_equality_of_opportunity", []) or []:
                    if risk_number(risk) not in have:
                        risks.append(risk); have.add(risk_number(risk)); added.append(risk)
            if added:
                risks.sort(key=risk_number)
                r["risks_to_equality_of_opportunity"] = json.dumps(risks, ensure_ascii=False)
                notes[r["record_id"]].append(f"risks added from merged strategies: {'; '.join(added)}")
                report.append({"provider": provider, "ukprn": ukprn, "record_id": r["record_id"],
                               "intervention": r["intervention_name"], "check": "merged risks",
                               "change": f"Added {'; '.join(added)}"})

        # 3. Reused codes: one code, several different activities, too few records
        names_by_code = defaultdict(set)
        for n, s in strategies.items():
            for act in s.get("activities", []) or []:
                m = CODE.match(str(act))
                # The activity's wording after the code, to tell different activities apart
                # (skipping cross-references such as "IST1; IST2 (same as strategy 5 activities)")
                rest = CODE.sub("", str(act))
                if m and not re.match(r"\s*[;,]", rest) and squash(rest):
                    names_by_code[m.group(1)].add(squash(rest))
        records_by_code = defaultdict(int)
        for r in recs:
            m = CODE.match(r.get("intervention_name", ""))
            if m:
                records_by_code[m.group(1)] += 1
        for code, names in sorted(names_by_code.items()):
            # Shortened and full versions of one name ("Triage Model", "RESOURCE - Triage Model") count once
            distinct = {n for n in names if not any(n != o and n in o for o in names)}
            if len(distinct) > 1 and records_by_code[code] < len(distinct):
                report.append({"provider": provider, "ukprn": ukprn, "record_id": "", "intervention": code,
                               "check": "reused code",
                               "change": f"{code} is used for {len(distinct)} different activities in the plan's strategies "
                                         f"but has {records_by_code[code]} record(s): check for missing records"})

        # 4. Target references and their text
        for r in recs:
            change = sync_targets(r, aims)
            if change:
                notes[r["record_id"]].append(change)
                report.append({"provider": provider, "ukprn": ukprn, "record_id": r["record_id"],
                               "intervention": r["intervention_name"], "check": "targets", "change": change})

        for r in recs:
            r["prep_notes"] = "; ".join(notes.get(r["record_id"], []))

    out = src.with_name(src.stem + "_prepared.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    rep = src.with_name(src.stem + "_prep_report.csv")
    with open(rep, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["provider", "ukprn", "record_id", "intervention", "check", "change"])
        w.writeheader()
        w.writerows(report)
    counts = defaultdict(int)
    for x in report:
        counts[x["check"]] += 1
    print(f"{len(rows)} records from {len(by_provider)} providers. "
          f"Pages changed or flagged: {counts['page']}; merged records given extra risks: {counts['merged risks']}; "
          f"reused codes to check: {counts['reused code']}; target fixes: {counts['targets']}.")
    print(f"Saved {out.name} (run the Claude review on this) and {rep.name} (what changed).")


if __name__ == "__main__":
    main()
