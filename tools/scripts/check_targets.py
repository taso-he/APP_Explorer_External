"""
Automated checks for the APP targets dataset.

Reads the target tables (Tables 5b, 5d and 5e) straight from each current
plan's PDF, without AI, and compares them field by field with the targets
dataset. It writes three spreadsheets:

  targets_check_by_field.csv  - one row per target and field that needs a look
  targets_check_by_target.csv - one row per target, with a result for each field
  targets_check_by_plan.csv   - one row per plan: targets found, missing, extra,
                                and the share of fields that match

The checks:
  1. Completeness  - every target in the PDF tables is in the dataset, and
                     every target in the dataset is in the PDF tables.
  2. Field match   - each copied field (aim, stage, groups, description,
                     units, baseline, final milestone and its year...) matches
                     the PDF. Spacing and line breaks are ignored.
  3. Sense checks  - values are numbers, the target year is inside the plan
                     period, and gap targets move in the right direction.

Only current plans (2025 onwards template) are checked. Past plans use a
different template and are skipped.

Usage (Windows, from the folder that holds this script):
  pip install pdfplumber pypdf
  python check_targets.py --targets targets.csv

Options:
  --institutions FILE  institutions.csv, for the plan links when the targets
                       file has none (default: institutions.csv beside it)
  --pdfs FOLDER   where to keep downloaded PDFs (default: pdfs)
  --out FOLDER    where to write the results (default: results)
  --limit N       only check the first N providers (good for a test run)
  --ukprn LIST    only check these providers, comma-separated
"""

import argparse
import csv
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

try:
    import pdfplumber
    from pypdf import PdfReader
except ImportError:
    sys.exit("A library is missing. Run: pip install pdfplumber pypdf")


# Template column headings, matched on their first words.
HEADERS = [
    ("aim", "aim"),
    ("reference number", "reference_number"),
    ("lifecycle stage", "lifecycle_stage"),
    ("characteristic", "characteristic"),
    ("target group", "target_group"),
    ("comparator group", "comparator_group"),
    ("description and commentary", "description_and_commentary"),
    ("is this target collaborative", "is_this_target_collaborative"),
    ("data source", "data_source"),
    ("baseline year", "baseline_year"),
    ("units", "units"),
    ("baseline data", "baseline_data"),
]
TEXT_FIELDS = [
    "aim", "lifecycle_stage", "characteristic", "target_group",
    "comparator_group", "description_and_commentary",
    "is_this_target_collaborative", "data_source", "baseline_year", "units",
]
NUMBER_FIELDS = ["baseline_data", "target"]
ALL_FIELDS = TEXT_FIELDS + NUMBER_FIELDS + ["when"]
# Template options that mean "see the description": the dataset may hold
# a cleaned value instead.
VAGUE = ("other", "not specified")
# Labels the dataset standardises (see clean_characteristics.gs).
RELABELLED = {
    "reported disability": "disability", "care experienced students": "care experienced",
    "mature": "age", "gender": "sex", "socio-economic": "deprivation (index of multiple deprivations [imd])",
    "socioeconomic": "deprivation (index of multiple deprivations [imd])", "school type": "entry qualifications",
    "state school": "entry qualifications", "multiple": "intersection of characteristics",
    "care leavers": "care experienced", "care leaver": "care experienced",
    "white economically disadvantaged males": "intersection of characteristics (ethnicity and deprivation and sex)",
}
# Template dropdown fields: in some PDFs, text from the next cell runs into
# these, so a PDF value that starts with the dataset value counts as a match.
DROPDOWNS = {"lifecycle_stage", "is_this_target_collaborative", "data_source", "baseline_year", "units"}
BLANK = {"", "not stated", "n/a", "na", "none"}
REF = re.compile(r"^PT[ASP]_\d+$")
GAP_WORDS = re.compile(r"\b(reduce|close|closing|eliminate|narrow|halve|remove)\b", re.I)


def one_line(text):
    return re.sub(r"\s+", " ", (text or "").replace("­", "")).strip()


def squash(text):
    """Lower case, letters and digits only: ignores spacing, punctuation and
    words split across lines."""
    return re.sub(r"[^a-z0-9]", "", one_line(text).lower())


def number(text):
    """First number in a value, plus whether it was written as a percentage."""
    t = one_line(str(text)).replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", t)
    if not m:
        return None, False
    return float(m.group()), "%" in t


def same_number(a, b):
    (x, xp), (y, yp) = number(a), number(b)
    if x is None or y is None:
        return None
    if abs(x - y) < 1e-6:
        return True
    # The PDF often shows a rounded value (4.85 for 4.854444)
    m = re.search(r"\.(\d+)", one_line(str(b)).replace(",", ""))
    places = len(m.group(1)) if m else 0
    if places >= 1 and abs(round(x, places) - y) < 1e-6:
        return True
    # 0.34 in one source and 34% in the other
    if xp != yp and (abs(x * 100 - y) < 1e-6 or abs(y * 100 - x) < 1e-6):
        return True
    return False


def download(url, path):
    if path.exists() and path.stat().st_size > 0:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            path.write_bytes(r.read())
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"    could not download: {e}")
        return False


class OlderLayout(Exception):
    """The plan uses the older target table layout (Target group / Underrepresented group)."""


def map_header(row):
    """Each field's column, counted from the reference number column, or
    None if this isn't a header row. Counting from the reference number copes
    with tables where the PDF adds blank columns."""
    cols, milestones = {}, []
    for i, cell in enumerate(row):
        h = one_line(cell).lower()
        if not h:
            continue
        if h.startswith("underrepresented group"):
            raise OlderLayout()
        # "milestone" is sometimes split across lines in the PDF ("mileston e")
        m = re.match(r"^(\d{4}-\d{2})\s*milestone", re.sub(r"(?<=[a-z])\s+(?=[a-z])", "", h))
        if m:
            milestones.append((i, m.group(1)))
            continue
        for start, field in HEADERS:
            if h.startswith(start) and field not in cols:
                cols[field] = i
                break
    if "reference_number" not in cols or "aim" not in cols:
        return None
    ref = cols["reference_number"]
    return {f: i - ref for f, i in cols.items()}, [(i - ref, y) for i, y in milestones]


def cell(row, ref_col, offset):
    i = ref_col + offset
    return one_line(row[i]) if 0 <= i < len(row) else ""


def read_pdf_targets(pdf_path):
    """Every target row in the PDF's target tables, keyed by reference number."""
    found, pages, unreadable = {}, [], 0
    layout = None  # the last header row seen
    with pdfplumber.open(pdf_path) as pdf:
        # pypdf finds the right pages quickly; pdfplumber then reads the tables.
        texts = [page.extract_text() or "" for page in PdfReader(pdf_path).pages]
        # The target tables sit in the "Fees, investments and targets" annex
        # at the end of the plan; start there when it can be found.
        starts = [i for i, t in enumerate(texts) if "fees, investments and targets" in t.lower()]
        first = starts[0] if starts else 0
        for n, page in enumerate(pdf.pages, start=1):
            text = texts[n - 1]
            if n - 1 < first or not re.search(r"PT[ASP]_\d", text):
                continue
            for table in page.extract_tables():
                last, last_col = None, None
                for row in table:
                    head = map_header(row)
                    if head:
                        layout = head
                        continue
                    if not layout:
                        continue
                    cols, milestones = layout
                    ref_col = next((i for i, c in enumerate(row) if REF.match(one_line(c))), None)
                    rec = None
                    if ref_col is None and last_col is not None and cell(row, last_col, cols.get("lifecycle_stage", 1)):
                        unreadable += 1  # a target row whose reference number is garbled in the PDF
                        continue
                    if ref_col is not None:
                        rec = {f: cell(row, ref_col, off) for f, off in cols.items()}
                    # A row with no aim and no stage is the end of the row above,
                    # spilling over in the PDF: add its words to that target.
                    if rec is None or (not rec.get("aim") and not rec.get("lifecycle_stage")):
                        col = ref_col if ref_col is not None else last_col
                        if last and col is not None:
                            for f, off in cols.items():
                                extra = cell(row, col, off)
                                if extra and f in TEXT_FIELDS:
                                    last[f] = (last.get(f, "") + " " + extra).strip()
                        continue
                    filled = [(y, cell(row, ref_col, off)) for off, y in milestones if cell(row, ref_col, off)]
                    rec["target"] = filled[-1][1] if filled else ""
                    rec["when"] = filled[-1][0] if filled else ""
                    rec["page"] = n
                    ref = rec["reference_number"]
                    if ref not in found:
                        found[ref] = rec
                        if n not in pages:
                            pages.append(n)
                    last, last_col = found[ref], ref_col
    return found, pages, unreadable


def compare(field, ours, theirs, clean):
    """Result for one field:
      match       - the same (a blank cell and 'Not stated' count as the same)
      minor       - only spacing or punctuation differ
      cleaned     - the dataset holds the cleaned value for a vague PDF value
      relabelled  - a characteristic label the dataset standardises
      cut short   - one version stops early (often a table cell that runs
                    over a page in the PDF): worth a quick look
      mismatch    - different"""
    if one_line(ours).lower() in BLANK and not one_line(theirs):
        return "match"
    if field in NUMBER_FIELDS:
        same = same_number(ours, theirs)
        if same is None:
            return "match" if squash(ours) == squash(theirs) else "mismatch"
        return "match" if same else "mismatch"
    if one_line(ours).lower() == one_line(theirs).lower():
        return "match"
    if squash(ours) == squash(theirs):
        return "minor"
    if clean and squash(ours) == squash(clean) and theirs.lower().startswith(VAGUE):
        return "cleaned"
    if field == "characteristic" and RELABELLED.get(one_line(theirs).lower()) == one_line(ours).lower():
        return "relabelled"
    a, b = squash(ours), squash(theirs)
    if field in DROPDOWNS and a and b.startswith(a):
        return "minor"
    if min(len(a), len(b)) >= 30 and (a.startswith(b) or b.startswith(a)):
        return "cut short"
    return "mismatch"


def sense_checks(t):
    issues = []
    for f in NUMBER_FIELDS:
        if t.get(f) and number(t[f])[0] is None:
            issues.append(f"{f} is not a number: '{t[f]}'")
    years = re.findall(r"(\d{4})-\d{2}", t.get("plan_period", ""))
    when = re.match(r"(\d{4})-\d{2}", t.get("when", ""))
    if len(years) == 2 and when and not int(years[0]) <= int(when.group(1)) <= int(years[1]):
        issues.append(f"target year {t['when']} is outside the plan period {t['plan_period']}")
    b, tg = number(t.get("baseline_data", ""))[0], number(t.get("target", ""))[0]
    if b is not None and tg is not None and "point" in t.get("units", "").lower():
        if GAP_WORDS.search(t.get("aim", "")) and tg > b:
            issues.append("a gap target that goes up: the aim says reduce or close, but the target is above the baseline")
    if "£" in t.get("aim", "") and "%" in t.get("aim", ""):
        issues.append("aim has a £ sign beside a percentage")
    return issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets", required=True, help="targets.csv, or the Streamlit targets export")
    ap.add_argument("--institutions")
    ap.add_argument("--pdfs", default="pdfs")
    ap.add_argument("--out", default="results")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ukprn")
    args = ap.parse_args()

    pdf_dir, out_dir = Path(args.pdfs), Path(args.out)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.targets, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("current_plan", "Yes").strip() == "Yes"]
    links = {}
    inst = Path(args.institutions) if args.institutions else Path(args.targets).with_name("institutions.csv")
    if inst.exists():
        with open(inst, encoding="utf-8-sig", newline="") as f:
            links = {r["ukprn"].strip(): r.get("plan_url", "").strip() for r in csv.DictReader(f)}
    plans = defaultdict(list)
    for r in rows:
        plans[r["ukprn"].strip()].append(r)
    wanted = list(plans)
    if args.ukprn:
        keep = {u.strip() for u in args.ukprn.split(",")}
        wanted = [u for u in wanted if u in keep]
    if args.limit:
        wanted = wanted[: args.limit]

    by_field, by_target, by_plan = [], [], []
    totals = Counter()
    for k, ukprn in enumerate(wanted, start=1):
        targets = plans[ukprn]
        name = targets[0].get("used_name") or targets[0].get("legal_name", "")
        url = targets[0].get("plan_url", "").strip() or links.get(ukprn, "")
        print(f"[{k}/{len(wanted)}] {name}", flush=True)
        plan = {"ukprn": ukprn, "provider": name, "targets_in_dataset": len(targets)}
        pdf_path = pdf_dir / f"{ukprn}.pdf"
        if not url or not download(url, pdf_path):
            plan["status"] = "no PDF"
            by_plan.append(plan)
            continue
        try:
            pdf_targets, pages, unreadable = read_pdf_targets(pdf_path)
        except OlderLayout:
            plan["status"] = "older table layout (Target group / Underrepresented group): check by hand"
            by_plan.append(plan)
            continue
        except Exception as e:
            plan["status"] = f"PDF could not be read: {e}"
            by_plan.append(plan)
            continue
        if not pdf_targets:
            plan["status"] = "target tables not found in PDF: check by hand"
            by_plan.append(plan)
            continue

        ours = {t["reference_number"].strip(): t for t in targets}
        missing = sorted(set(pdf_targets) - set(ours))
        extra = sorted(set(ours) - set(pdf_targets))
        plan.update(status="checked", targets_in_pdf=len(pdf_targets), table_pages=", ".join(map(str, pages)),
                    missing_from_dataset=", ".join(missing), not_in_pdf_tables=", ".join(extra),
                    unreadable_rows=unreadable or "")
        results = Counter()
        for ref, t in sorted(ours.items()):
            line = {"ukprn": ukprn, "provider": name, "reference_number": ref}
            p = pdf_targets.get(ref)
            if not p:
                line["overall"] = "not found in PDF tables"
                by_target.append(line)
                by_field.append({"ukprn": ukprn, "provider": name, "reference_number": ref, "page": "",
                                 "field": "", "check": "not found in PDF tables",
                                 "dataset_value": t.get("aim", ""), "pdf_value": "", "similarity": ""})
                continue
            line["page"] = p["page"]
            bad = 0
            for field in ALL_FIELDS:
                if field not in p:
                    line[field] = "not in PDF table"
                    continue
                res = compare(field, t.get(field, ""), p[field], t.get(field + "_clean", ""))
                line[field] = res
                results[res] += 1
                if res in ("mismatch", "cut short"):
                    bad += 1
                    ratio = SequenceMatcher(None, one_line(t.get(field, "")), p[field]).ratio()
                    by_field.append({"ukprn": ukprn, "provider": name, "reference_number": ref, "page": p["page"],
                                     "field": field, "check": "different" if res == "mismatch" else "one version cut short", "dataset_value": t.get(field, ""),
                                     "pdf_value": p[field], "similarity": f"{ratio:.0%}"})
            issues = sense_checks(t)
            for issue in issues:
                by_field.append({"ukprn": ukprn, "provider": name, "reference_number": ref, "page": p["page"],
                                 "field": "", "check": "sense check", "dataset_value": issue, "pdf_value": "",
                                 "similarity": ""})
            line["sense_checks"] = "; ".join(issues)
            line["overall"] = "needs a look" if bad or issues else "ok"
            by_target.append(line)
        for ref in missing:
            p = pdf_targets[ref]
            by_field.append({"ukprn": ukprn, "provider": name, "reference_number": ref, "page": p["page"],
                             "field": "", "check": "missing from dataset", "dataset_value": "",
                             "pdf_value": p.get("aim", ""), "similarity": ""})
        checked = sum(results.values())
        ok = results["match"] + results["minor"] + results["cleaned"] + results["relabelled"]
        plan["fields_checked"] = checked
        plan["fields_matching"] = ok
        plan["match_rate"] = f"{ok / checked:.0%}" if checked else ""
        by_plan.append(plan)
        totals.update(results)
        totals["plans"] += 1
        totals["missing"] += len(missing)
        totals["extra"] += len(extra)

    def write(name, data, fields):
        with open(out_dir / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    write("targets_check_by_field.csv", by_field,
          ["ukprn", "provider", "reference_number", "page", "check", "field", "dataset_value", "pdf_value", "similarity"])
    write("targets_check_by_target.csv", by_target,
          ["ukprn", "provider", "reference_number", "page", "overall"] + ALL_FIELDS + ["sense_checks"])
    write("targets_check_by_plan.csv", by_plan,
          ["ukprn", "provider", "status", "targets_in_dataset", "targets_in_pdf", "table_pages",
           "missing_from_dataset", "not_in_pdf_tables", "unreadable_rows", "fields_checked", "fields_matching", "match_rate"])

    checked = sum(totals[r] for r in ("match", "minor", "cleaned", "relabelled", "cut short", "mismatch"))
    print()
    print(f"Plans checked: {totals['plans']} of {len(wanted)} "
          f"({sum(1 for p in by_plan if p['status'] != 'checked')} need checking by hand: see targets_check_by_plan.csv)")
    if checked:
        bad = totals["mismatch"] + totals["cut short"]
        print(f"Fields matching the PDF: {(checked - bad) / checked:.1%} of {checked}")
        print(f"  same: {totals['match']} | spacing or punctuation only: {totals['minor']} | "
              f"cleaned value used: {totals['cleaned']} | standard label used: {totals['relabelled']}")
        print(f"  to look at: {totals['mismatch']} different, {totals['cut short']} cut short")
    print(f"Targets in the PDF but missing from the dataset: {totals['missing']}")
    print(f"Targets in the dataset but not found in the PDF tables: {totals['extra']}")
    print(f"Results saved in {out_dir.resolve()}")


if __name__ == "__main__":
    main()
