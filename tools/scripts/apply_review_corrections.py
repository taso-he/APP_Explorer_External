"""
Apply the Claude review's corrections to an interventions export, and list what a person should check.

A correction is applied when Python found Claude's quote in the plan (quote_verified) and Claude gave a
corrected value. Everything else Claude raised goes on a to-check list:

  person   needs a decision: Unsure verdicts, corrections whose quote couldn't be found, records Claude
           says are not interventions or are duplicates (left out of the corrected file), and table rows
           Claude thinks have no record (from the _missing_records file)
  sample   one in ten of the applied corrections, chosen at random, for a spot check of Claude's work,
           plus every correction whose quote is on an image page (Python can't read it to check)

Python also tidies two things so they don't reach a person:
  - an Unsure or other verdict whose "correction" is the value already there is dropped
  - linked_targets_text is always set from linked_target_ids and the targets list (data\\targets.csv),
    and target references that aren't in that list are dropped, so the text can't disagree with the ids

Writes, next to the export:
  <export>_corrected.csv   the export with corrections applied, records left out as above, and a
                           qa_status column (feeds taso-frontend/build_data.py)
  <export>_to_check.csv    the to-check list, with the plan page and Claude's quote

Usage (Windows, from the repository folder):
  python taso-handover\\scripts\\apply_review_corrections.py "C:\\path\\to\\export_prepared.csv" claude-20261102-101500
Options:
  --results FOLDER   where the review saved its CSV files (default: taso-handover\\scripts\\claude_review_results)
  --sample N         spot-check one in N applied corrections (default 10; 0 for none)
"""

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from review_interventions_claude import load_targets, same_value, sync_targets  # noqa: E402
CORRECTABLE = {"Partly correct", "Incorrect", "Missing"}


def read(path):
    if not path.exists():
        sys.exit(f"Can't find {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export")
    ap.add_argument("run_id")
    ap.add_argument("--results", default=str(HERE / "claude_review_results"))
    ap.add_argument("--sample", type=int, default=10)
    args = ap.parse_args()

    src, results = Path(args.export), Path(args.results)
    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = [r for r in reader if r.get("record_id")]
    reviews = read(results / f"{args.run_id}_field_reviews.csv")
    checks = {c["record_id"]: c for c in read(results / f"{args.run_id}_record_checks.csv")}
    missing_path = results / f"{args.run_id}_missing_records.csv"
    missing = read(missing_path) if missing_path.exists() else []

    by_id = {r["record_id"]: r for r in rows}
    to_check, applied = [], []
    changes = defaultdict(int)
    needs_person = set()

    def flag(route, r, field, reason, value="", quote="", page=""):
        to_check.append({"route": route, "provider": r.get("provider", ""), "ukprn": r.get("ukprn", ""),
                         "record_id": r.get("record_id", ""), "intervention": r.get("intervention_name", ""),
                         "field": field, "reason": reason, "current_value": r.get(field, "") if field in r else "",
                         "claude_value": value, "evidence_quote": quote, "evidence_page": page})

    aims = load_targets()
    image_checked = []
    for v in reviews:
        r = by_id.get(v["record_id"])
        if r is None or v["status"] == "Correct":
            continue
        if same_value(r.get(v["field"], ""), v["corrected_value"]):
            continue  # the "correction" is the value already there
        if v["field"] == "linked_targets_text" and aims.get(r.get("ukprn", "").strip()):
            continue  # set from linked_target_ids below
        verified = v.get("quote_verified") in ("True", "image")
        if v["status"] in CORRECTABLE and verified and v["corrected_value"].strip():
            if v["field"] not in fields:
                continue
            item = {"r": r, "v": v, "old": r[v["field"]], "name": r["intervention_name"]}
            r[v["field"]] = v["corrected_value"]
            changes[r["record_id"]] += 1
            applied.append(item)
            if v.get("quote_verified") == "image":
                image_checked.append(item)
        else:
            reason = ("Claude was unsure" if v["status"] == "Unsure" or not v["corrected_value"].strip()
                      else "Claude's quote wasn't found in the plan")
            needs_person.add(r["record_id"])
            flag("person", r, v["field"], f"{reason} ({v['status']}{', ' + v['error_type'] if v['error_type'] else ''})",
                 v["corrected_value"], v["evidence_quote"], v["evidence_page"])

    # Target text always follows the target references
    for r in rows:
        sync_targets(r, aims)

    kept, left_out = [], 0
    for r in rows:
        c = checks.get(r["record_id"])
        status = c["status"] if c else "Yes"
        # A duplicate is only left out when the record it duplicates is kept, so the activity isn't lost
        if status == "Duplicate" and (checks.get(c["duplicate_of"], {}).get("status") != "Yes"
                                      or c["duplicate_of"] not in by_id):
            needs_person.add(r["record_id"])
            flag("person", r, "(whole record)", f"Kept: Claude says this duplicates {c['duplicate_of'] or 'another record'}, "
                 f"but that record isn't in this run. Check whether it repeats another record. {c['reason']}".strip())
            status = "Yes"
        if status in ("Not an intervention", "Duplicate"):
            left_out += 1
            why = f"Duplicate of {c['duplicate_of']}" if status == "Duplicate" else "Not an intervention"
            flag("person", r, "(whole record)", f"Left out of the corrected file: {why}. {c['reason']}".strip())
            continue
        if status == "Unsure":
            needs_person.add(r["record_id"])
            flag("person", r, "(whole record)", f"Claude was unsure whether this is an intervention. {c['reason']}".strip())
        n = changes.get(r["record_id"], 0)
        r["qa_status"] = ("Checked by the automated reviewer" + (f"; {n} correction{'s' if n != 1 else ''} applied" if n else "")
                          + ("; some fields awaiting a person's check" if r["record_id"] in needs_person else ""))
        kept.append(r)

    for m in missing:
        flag("person", {"provider": m["provider"], "ukprn": m["ukprn"], "intervention_name": m["activity"]},
             "(missing record)", f"Row of strategy {m['strategy'][:60]} with no record"
             + ("" if m.get("quote_verified") == "True" else " (quote not found: check it exists)"),
             "", m["evidence_quote"], m["evidence_page"])

    sampled = []
    if args.sample and applied:
        rng = random.Random(args.run_id)  # the same run always gives the same sample
        sampled = rng.sample(applied, max(1, len(applied) // args.sample))
        # Corrections checked against an image page always get a spot check
        sampled += [i for i in image_checked if i not in sampled]
        for item in sampled:
            r, v = item["r"], item["v"]
            to_check.append({"route": "sample", "provider": r["provider"], "ukprn": r["ukprn"],
                             "record_id": r["record_id"], "intervention": item["name"], "field": v["field"],
                             "reason": f"Spot check of an applied correction ({v['status']}, {v['error_type']})"
                                       + ("; the quote is on an image page" if v.get("quote_verified") == "image" else ""),
                             "current_value": item["old"], "claude_value": v["corrected_value"],
                             "evidence_quote": v["evidence_quote"], "evidence_page": v["evidence_page"]})

    if "qa_status" not in fields:
        fields.append("qa_status")
    out = src.with_name(src.stem + "_corrected.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(kept)
    chk = src.with_name(src.stem + "_to_check.csv")
    to_check.sort(key=lambda x: (x["route"] != "person", x["provider"], x["record_id"]))
    with open(chk, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["route", "provider", "ukprn", "record_id", "intervention", "field", "reason",
                                          "current_value", "claude_value", "evidence_quote", "evidence_page"])
        w.writeheader()
        w.writerows(to_check)

    people = sum(1 for x in to_check if x["route"] == "person")
    print(f"{len(applied)} corrections applied to {len(changes)} records; {left_out} records left out "
          f"(not interventions or duplicates); {len(kept)} records in {out.name}.")
    print(f"To check in {chk.name}: {people} items needing a person, {len(sampled)} spot checks.")


if __name__ == "__main__":
    main()
