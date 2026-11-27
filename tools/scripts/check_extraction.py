"""
Automated checks for the interventions extraction.

Run this after each extraction. It checks every extracted record against the
APP PDF and the targets dataset, and writes two spreadsheets:

  checks_by_record.csv - one row per record, with a result for each check
  checks_by_plan.csv   - one row per plan, with totals and the strategy-count check

The checks:
  1. Description match - is the description copied word for word, and on the
     stated page? (This also checks the page number.)
  2. Valid values      - required fields filled, page within the document,
     demographic and lifecycle codes on the fixed lists.
  3. Duplicates        - same provider and the same description, or the same
     name under the same strategies.
  4. Target links      - does every target ID exist in that provider's targets?
     Also looks up each target's aim text.
  5. Strategy counts   - does every activity in the AI's strategy map have a
     matching record? (Plan level.)

Usage (Windows, from the taso-handover folder):
  pip install pypdf
  python scripts\\check_extraction.py --extraction "path\\to\\export.csv" ^
      --pdfs "path\\to\\APP PDFs" --targets data\\targets.csv

Works with the new trimmed field names and with the older export format
(primary_evidence_quote, page_reference, app_target_identifiers).
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("pypdf is not installed. Run: pip install pypdf")


DEMOGRAPHIC_CODES = {
    "age", "disability", "ethnicity", "sex", "lgbtq", "area_based", "fsm",
    "low_income", "first_in_family", "care_experienced", "estranged", "carer",
    "parents", "military", "gtrsb", "refugee_asylum", "child_in_need",
    "ex_prisoner", "religion", "commuter", "entry_route", "mode_of_study", "mental_health", "abcs", "all_students", "other",
}
LIFECYCLE_CODES = {
    "pre_entry_attainment", "access", "transition", "continuation",
    "completion", "attainment", "progression", "whole_lifecycle",
}

# Each field can come under its new name or its older one.
FIELDS = {
    "name": ["intervention_name", "intervention_name_exact"],
    "description": ["intervention_description"],
    "quote": ["primary_evidence_quote"],
    "page": ["page", "page_reference"],
    "strategy": ["intervention_strategy", "intervention_strategies"],
    "target_ids": ["linked_target_ids", "app_target_identifiers"],
    "demographics": ["target_demographics"],
    "lifecycle": ["lifecycle_stages"],
    "source_section": ["source_section"],
    "strategies_found": ["strategies_found"],
    "source_file": ["source_file"],
    "ukprn": ["ukprn"],
    "provider": ["provider"],
}

EMPTY = {"", "not stated", "not_stated", "none", "null", "n/a", "[]"}


def get(row, key):
    for column in FIELDS[key]:
        value = row.get(column)
        if value is not None and str(value).strip().lower() not in EMPTY:
            return value if not isinstance(value, str) else value.strip()
    return ""


def as_list(value):
    """Lists arrive as JSON text in a CSV, e.g. '["PTA_1", "PTS_2"]'."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [part.strip() for part in re.split(r"[;,]", str(value)) if part.strip()]


def squash(text):
    """Letters and digits only, lower case. Makes the match ignore spacing,
    punctuation, curly quotes and words split across lines."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def words(text):
    return [w for w in re.split(r"\s+", str(text).strip()) if squash(w)]


def ukprn_from(text):
    match = re.search(r"(\d{8})(?:\.pdf)?\s*$", str(text))
    return match.group(1) if match else ""


def load_records(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):  # a single plan's raw output
            records = data.get("interventions", [])
            for record in records:
                record.setdefault("strategies_found", json.dumps(data.get("strategies_found", [])))
            return records
        return data
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_targets(path):
    """Returns {(ukprn, reference): aim} for current plans."""
    targets = {}
    if not path:
        return targets
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("current_plan", "Yes").strip().lower() not in ("yes", "true", "1"):
                continue
            key = (str(row["ukprn"]).strip(), str(row["reference_number"]).strip().upper())
            targets[key] = (row.get("aim") or "").strip()
    return targets


class PdfText:
    """Reads each PDF once and keeps the text of every page."""

    def __init__(self, folder, single_pdf=None):
        self.folder = Path(folder) if folder else None
        self.single_pdf = Path(single_pdf) if single_pdf else None
        self.cache = {}

    def find(self, source_file, ukprn):
        if self.single_pdf:
            return self.single_pdf
        if not self.folder:
            return None
        if source_file and (self.folder / source_file).exists():
            return self.folder / source_file
        if ukprn:
            matches = sorted(self.folder.glob(f"*{ukprn}*.pdf"))
            if matches:
                return matches[-1]
        return None

    def pages(self, pdf_path):
        if pdf_path not in self.cache:
            reader = PdfReader(str(pdf_path))
            self.cache[pdf_path] = [squash(page.extract_text() or "") for page in reader.pages]
        return self.cache[pdf_path]


def check_description(text, stated_page, pages):
    """Returns (result, page_found, detail)."""
    if not text:
        return "no description", "", ""
    target = squash(text)
    found_on = [i + 1 for i, page in enumerate(pages) if target in page]
    if found_on:
        if stated_page in found_on:
            return "match on stated page", stated_page, ""
        return "match on a different page", found_on[0], f"stated page {stated_page or 'missing'}"

    # Not a full match: how far through does it match before it differs?
    text_words = words(text)
    whole = "".join(pages)
    matched = 0
    for n in range(len(text_words), 0, -1):
        if squash(" ".join(text_words[:n])) in whole:
            matched = n
            break
    if matched >= 5:
        prefix = squash(" ".join(text_words[:matched]))
        page = next((i + 1 for i, p in enumerate(pages) if prefix in p), "")
        differs_at = " ".join(text_words[matched:matched + 8])
        return ("partial match", page,
                f"first {matched} of {len(text_words)} words match; differs at: \"{differs_at}...\"")
    return "not found", "", ""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extraction", required=True, help="Extraction export (CSV or JSON)")
    parser.add_argument("--pdfs", help="Folder holding the APP PDFs")
    parser.add_argument("--pdf", help="A single APP PDF, if checking one plan")
    parser.add_argument("--targets", help="Targets CSV (e.g. data/targets.csv)")
    parser.add_argument("--out", help="Folder for the results (default: next to the extraction file)")
    args = parser.parse_args()

    if not args.pdfs and not args.pdf:
        sys.exit("Give either --pdfs (a folder) or --pdf (one file).")

    records = load_records(args.extraction)
    targets = load_targets(args.targets)
    pdfs = PdfText(args.pdfs, args.pdf)
    out_dir = Path(args.out) if args.out else Path(args.extraction).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Number records within each plan, in the order they came back.
    counters = Counter()
    results = []
    by_plan = defaultdict(list)

    for row in records:
        source_file = get(row, "source_file")
        ukprn = str(get(row, "ukprn") or ukprn_from(source_file) or ukprn_from(args.pdf or "")).strip()
        counters[ukprn] += 1
        record_id = row.get("record_id") or f"{ukprn}-{counters[ukprn]:02d}"

        uses_quote = bool(get(row, "quote"))  # older export format
        evidence = get(row, "quote") if uses_quote else get(row, "description")
        page_value = str(get(row, "page"))
        stated_page = int(page_value) if page_value.isdigit() else None

        result = {
            "record_id": record_id,
            "provider": get(row, "provider"),
            "ukprn": ukprn,
            "intervention_name": get(row, "name"),
            "stated_page": stated_page or "",
        }

        # 1. Description match
        pdf_path = pdfs.find(source_file, ukprn)
        if pdf_path:
            pages = pdfs.pages(pdf_path)
            outcome, page_found, detail = check_description(evidence, stated_page, pages)
        else:
            pages, outcome, page_found, detail = [], "PDF not found", "", ""
        result.update({
            "checked_field": "primary_evidence_quote" if uses_quote else "intervention_description",
            "description_check": outcome,
            "page_found": page_found,
            "description_detail": detail,
        })

        # 2. Valid values
        problems = []
        for key, label in (("name", "name"), ("description", "description"), ("strategy", "strategy"), ("page", "page")):
            if key == "description" and uses_quote:
                key = "quote"
            if not get(row, key):
                problems.append(f"{label} missing")
        if stated_page and pages and not 1 <= stated_page <= len(pages):
            problems.append(f"page {stated_page} is outside the document (1-{len(pages)})")
        if page_value and not stated_page:
            problems.append(f"page is not a number: {page_value}")
        for key, allowed, label in (("demographics", DEMOGRAPHIC_CODES, "demographic"),
                                    ("lifecycle", LIFECYCLE_CODES, "lifecycle")):
            bad = [code for code in as_list(get(row, key)) if code not in allowed]
            if bad:
                problems.append(f"unknown {label} code: {', '.join(bad)}")
        result["valid_values"] = "pass" if not problems else "fail"
        result["valid_values_detail"] = "; ".join(problems)

        # 4. Target links (and look up the aim text)
        target_ids = [t.upper() for t in as_list(get(row, "target_ids"))]
        unknown = [t for t in target_ids if (ukprn, t) not in targets] if targets else []
        if not targets:
            result["target_links"] = "not checked (no targets file)"
        elif not target_ids:
            result["target_links"] = "no target IDs"
        else:
            result["target_links"] = "pass" if not unknown else "fail"
        result["unknown_target_ids"] = ", ".join(unknown)
        result["linked_targets_text_lookup"] = " | ".join(
            f"{t}: {targets[(ukprn, t)]}" for t in target_ids if (ukprn, t) in targets)

        result["_strategy_set"] = tuple(sorted(squash(s)[:1] + squash(s)[1:] for s in as_list(get(row, "strategy"))))
        result["_name_key"] = squash(get(row, "name"))
        result["_desc_key"] = squash(evidence)[:300]
        result["_section"] = get(row, "source_section")
        result["_strategies_found"] = get(row, "strategies_found")
        results.append(result)
        by_plan[ukprn].append(result)

    # 3. Duplicates (within each plan)
    for plan_rows in by_plan.values():
        for i, a in enumerate(plan_rows):
            dupes = []
            for j, b in enumerate(plan_rows):
                if i == j:
                    continue
                same_text = a["_desc_key"] and a["_desc_key"] == b["_desc_key"]
                same_name = a["_name_key"] and a["_name_key"] == b["_name_key"]
                same_strategies = set(a["_strategy_set"]) & set(b["_strategy_set"])
                if same_text or (same_name and same_strategies):
                    dupes.append(b["record_id"])
            a["possible_duplicate_of"] = ", ".join(dupes)

    # 5. Strategy counts (per plan)
    plan_rows_out = []
    for ukprn, plan_rows in by_plan.items():
        strategy_map = []
        raw = next((r["_strategies_found"] for r in plan_rows if r["_strategies_found"]), "")
        try:
            strategy_map = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            pass
        mapped_names = Counter()
        for strategy in strategy_map or []:
            for name in strategy.get("activities") or strategy.get("activity_rows") or []:
                mapped_names[squash(name)] += 1
        table_records = Counter(r["_name_key"] for r in plan_rows
                                if "outside" not in str(r["_section"]).lower()
                                and str(r["_section"]).lower() != "elsewhere_in_plan")
        # An activity listed under several strategies should have one record that
        # names all of them, so only a missing name counts as a failure.
        unmatched = [name for name in mapped_names if not table_records[name]]
        outcomes = Counter(r["description_check"] for r in plan_rows)
        plan_rows_out.append({
            "ukprn": ukprn,
            "provider": plan_rows[0]["provider"],
            "records": len(plan_rows),
            "activities_in_strategy_map": sum(mapped_names.values()),
            "strategy_count_check": ("no strategy map" if not mapped_names
                                     else "pass" if not unmatched else "fail"),
            "map_activities_without_a_record": len(unmatched),
            "description_match_stated_page": outcomes["match on stated page"],
            "description_match_other_page": outcomes["match on a different page"],
            "description_partial": outcomes["partial match"],
            "description_not_found": outcomes["not found"],
            "description_match_rate": f"{(outcomes['match on stated page'] + outcomes['match on a different page']) / len(plan_rows):.0%}",
            "page_correct_rate": f"{outcomes['match on stated page'] / len(plan_rows):.0%}",
            "valid_values_failures": sum(r["valid_values"] == "fail" for r in plan_rows),
            "possible_duplicates": sum(bool(r["possible_duplicate_of"]) for r in plan_rows),
            "target_link_failures": sum(r["target_links"] == "fail" for r in plan_rows),
        })

    # Overall result per record
    for r in results:
        issues = []
        if r["description_check"] != "match on stated page":
            issues.append(r["description_check"])
        if r["valid_values"] == "fail":
            issues.append("invalid values")
        if r["possible_duplicate_of"]:
            issues.append("possible duplicate")
        if r["target_links"] == "fail":
            issues.append("unknown target ID")
        r["needs_review"] = "yes" if issues else "no"
        r["issues"] = "; ".join(issues)

    record_columns = ["record_id", "provider", "ukprn", "intervention_name", "needs_review", "issues",
                      "checked_field", "description_check", "stated_page", "page_found", "description_detail",
                      "valid_values", "valid_values_detail", "possible_duplicate_of",
                      "target_links", "unknown_target_ids", "linked_targets_text_lookup"]
    with (out_dir / "checks_by_record.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=record_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    with (out_dir / "checks_by_plan.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(plan_rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(plan_rows_out)

    for plan in plan_rows_out:
        print(f"\n{plan['provider'] or plan['ukprn']}: {plan['records']} records")
        print(f"  Description found word for word: {plan['description_match_rate']}"
              f" (on the stated page: {plan['page_correct_rate']})")
        print(f"  Strategy map check: {plan['strategy_count_check']}"
              f" ({plan['map_activities_without_a_record']} activities in the map without a record)")
        print(f"  Invalid values: {plan['valid_values_failures']} | Possible duplicates: {plan['possible_duplicates']}"
              f" | Unknown target IDs: {plan['target_link_failures']}")
    flagged = sum(r["needs_review"] == "yes" for r in results)
    print(f"\n{flagged} of {len(results)} records need a look. Results saved in {out_dir}")


if __name__ == "__main__":
    main()
