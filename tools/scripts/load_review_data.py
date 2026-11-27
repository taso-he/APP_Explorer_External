"""
Load a checked extraction into Supabase for the review page and the TASO page.

Reads the three files the earlier steps wrote (in taso-handover\\scripts\\extractions):
  <name>_prepared.csv            every record before Claude's corrections
  <name>_prepared_corrected.csv  the records with Claude's corrections applied
  <name>_prepared_to_check.csv   the items a person needs to decide, and the spot checks

and loads:
  interventions_working   one row per record. Records Claude left out (duplicates, not an
                          intervention) are loaded too, marked removed, so a reviewer can restore them.
  qa_person_checks        the review queue, one row per item

Records and items already in Supabase are left as they are, so decisions are never overwritten
and running this twice is safe. The TASO page shows the interventions straight away, with an
"Awaiting review" tag on any that still have open items.

Usage (Windows, from the repository folder):
  python taso-handover\\scripts\\load_review_data.py taso-handover\\scripts\\extractions\\extraction_latest_2026-10-31_prepared.csv claude-20261031-105950

Needs SUPABASE_URL and SUPABASE_SERVICE_KEY, as for the Claude review's --upload.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

FIELDS = ["intervention_name", "activity_status", "intervention_description", "intervention_strategy",
          "students_targeted_exact", "target_demographics", "demographics_combined", "lifecycle_stages",
          "linked_target_ids", "linked_targets_text", "risks_to_equality_of_opportunity", "page"]


def read(path):
    if not path.exists():
        sys.exit(f"Can't find {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def kind_of(item):
    """What sort of decision the item needs, from the to-check list's route, field and reason."""
    if item["route"] == "sample":
        return "sample"
    if item["field"] == "(missing record)":
        return "missing"
    if item["field"] == "(whole record)":
        reason = item["reason"]
        if reason.startswith("Left out"):
            return "removed"
        if reason.startswith("Kept:"):
            return "kept_duplicate"
        return "record_unsure"
    return "field"


def upload(table, rows):
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY need to be set (see the guide), then open a new Command Prompt.")
    headers = {"apikey": key, "Content-Type": "application/json",
               # Add new rows only: anything already loaded, and any decision on it, stays as it is
               "Prefer": "resolution=ignore-duplicates,return=minimal"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    for i in range(0, len(rows), 200):
        req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/{table}", method="POST", headers=headers,
                                     data=json.dumps(rows[i:i + 200]).encode("utf-8"))
        try:
            with urllib.request.urlopen(req, timeout=120):
                pass
        except urllib.error.HTTPError as e:
            sys.exit(f"Supabase refused the upload to {table} (error {e.code}): {e.read().decode('utf-8', 'replace')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prepared", help="the _prepared.csv file")
    ap.add_argument("run_id", help="the Claude review run, e.g. claude-20261031-105950")
    args = ap.parse_args()

    prepared_path = Path(args.prepared)
    prepared = read(prepared_path)
    corrected = {r["record_id"]: r for r in read(prepared_path.with_name(prepared_path.stem + "_corrected.csv"))}
    to_check = read(prepared_path.with_name(prepared_path.stem + "_to_check.csv"))
    left_out = {i["record_id"]: i["reason"] for i in to_check if kind_of(i) == "removed"}

    working = []
    for r in prepared:
        kept = corrected.get(r["record_id"])
        src = kept or r
        working.append({
            "record_id": r["record_id"], "ukprn": r["ukprn"].strip(), "provider": r["provider"],
            "extraction_run_id": r.get("extraction_run_id", ""), **{f: src.get(f, "") for f in FIELDS},
            "removed": kept is None,
            "removed_reason": left_out.get(r["record_id"], "Left out by the automated review") if kept is None else None,
            "qa_status": src.get("qa_status") or "Checked by the automated reviewer",
        })

    queue = []
    for i in to_check:
        kind = kind_of(i)
        key = "|".join([args.run_id, kind, i["record_id"], i["field"], i["intervention"], i["evidence_quote"][:80]])
        page = str(i.get("evidence_page") or "").strip()
        queue.append({
            "check_id": hashlib.sha1(key.encode("utf-8")).hexdigest()[:20], "source": "claude",
            "review_run_id": args.run_id, "kind": kind, "record_id": i["record_id"] or None,
            "ukprn": i["ukprn"].strip(), "provider": i["provider"], "intervention": i["intervention"],
            "field": None if i["field"].startswith("(") else i["field"], "reason": i["reason"],
            "current_value": i["current_value"], "suggested_value": i["claude_value"],
            "evidence_quote": i["evidence_quote"], "evidence_page": int(page) if page.isdigit() else None,
        })
    # Two identical items (same record, field and quote) would share an ID: keep one
    queue = list({q["check_id"]: q for q in queue}.values())

    upload("interventions_working", working)
    upload("qa_person_checks", queue)
    kinds = {}
    for q in queue:
        kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
    print(f"Loaded {len(working)} records ({sum(1 for w in working if w['removed'])} marked removed) "
          f"and {len(queue)} review items: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + ".")
    print("The TASO page now shows these interventions. Open the review page to work through the items.")


if __name__ == "__main__":
    main()
