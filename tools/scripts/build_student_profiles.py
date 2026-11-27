"""
Build each provider's undergraduate student profile from the OfS size and shape
of provision data, in the same form as the Institutions tab of the Open APP
spreadsheet and the `profile` column of the TASO site's Supabase table.

This replaces the hand calculation that used to live in the spreadsheet's
Demographics tab. It was rebuilt in November 2026 and checked against that tab:
for every provider it reproduces the Institutions tab percentages exactly.

How the percentages are worked out
  * Only undergraduates count: full-time + part-time + apprenticeship.
  * Only the "All students" cohort is used.
  * Suppressed OfS values ([DPL], [DPH], [DP], [low], [none], [N/A] ...) count as 0.
  * Each percentage = students in the group / students in the characteristic.
    Most characteristics leave "unknown" out of the denominator (IMD, TUNDRA,
    free school meals, entry qualifications, sexual orientation, sex, domicile),
    because that is how the original spreadsheet did it. Age, disability and
    ethnicity keep everyone in.
  * Providers with no undergraduate data for a characteristic get a blank.
  * Counts are rounded to the nearest 10 by the OfS, so small providers'
    figures are approximate.

Usage (Python 3.9+, no extra packages):

    python build_student_profiles.py "OfS_size_and_shape.csv"
    python build_student_profiles.py "OfS_size_and_shape.csv" --numbers "OfS_Student_numbers_all_providers.csv"

Outputs, written next to the input file:
    student_profiles.csv          one row per provider, columns in the same order as
                                  the Institutions tab (% mature to Tundra Q5, then the
                                  undergraduate totals if --numbers is given).
                                  Paste values into the Sheet by matching UKPRN.
    student_profiles_supabase.sql an UPDATE for public.site_providers (profile and
                                  ug_students) for the TASO site.

If the OfS file has more than one BASE_YEAR, the latest is used (or pass --year).
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

UG_COLS = ("FT_UG_COUNT", "PT_UG_COUNT", "APPR_UG_COUNT")


def unknown(a):
    a = a.lower()
    return "unknown" in a or "refused" in a or "not applicable" in a


# Output column -> (OfS characteristic, which attributes count, exclude unknowns from the denominator?)
SPEC = [
    ("% mature UG (21+)", "Age on entry - UG", lambda a: a != "Under 21 years", False),
    ("IMD Q1", "Deprivation quintile (IMD)", lambda a: a == "Quintile 1", True),
    ("IMD Q2", "Deprivation quintile (IMD)", lambda a: a == "Quintile 2", True),
    ("IMD Q3", "Deprivation quintile (IMD)", lambda a: a == "Quintile 3", True),
    ("IMD Q4", "Deprivation quintile (IMD)", lambda a: a == "Quintile 4", True),
    ("IMD Q5", "Deprivation quintile (IMD)", lambda a: a == "Quintile 5", True),
    ("Disability", "Disability type", lambda a: not a.lower().startswith("no disability"), False),
    ("Asian", "Ethnicity", lambda a: a == "Asian", False),
    ("Black", "Ethnicity", lambda a: a == "Black", False),
    ("Mixed", "Ethnicity", lambda a: a == "Mixed", False),
    ("Other", "Ethnicity", lambda a: a == "Other", False),
    ("White", "Ethnicity", lambda a: a == "White", False),
    ("GEM", "Ethnicity", lambda a: a in ("Asian", "Black", "Mixed", "Other"), False),
    ("Free School Meals", "Eligibility for free school meals", lambda a: a == "Eligible", True),
    ("UK", "Domicile", lambda a: a == "UK", True),
    ("A-level", "Entry qualifications", lambda a: a.startswith("A-levels"), True),
    ("BTEC", "Entry qualifications", lambda a: a.startswith("BTECs"), True),
    ("Access / Foundation", "Entry qualifications", lambda a: a.startswith("Access courses"), True),
    ("Male", "Sex", lambda a: a == "Male", True),
    ("Queer (LGB)", "Sexual orientation", lambda a: a == "Lesbian, gay or bisexual (LGB)", True),
    ("Tundra Q1", "TUNDRA (MSOA)", lambda a: a == "Quintile 1", True),
    ("Tundra Q2", "TUNDRA (MSOA)", lambda a: a == "Quintile 2", True),
    ("Tundra Q3", "TUNDRA (MSOA)", lambda a: a == "Quintile 3", True),
    ("Tundra Q4", "TUNDRA (MSOA)", lambda a: a == "Quintile 4", True),
    ("Tundra Q5", "TUNDRA (MSOA)", lambda a: a == "Quintile 5", True),
]
CHARS = {c for _, c, _, _ in SPEC}

# Institutions tab column -> key in the TASO site's profile (stored as % to 2 dp)
SITE_PROFILE = {"mature_pct": "% mature UG (21+)", "imd_q1": "IMD Q1", "imd_q2": "IMD Q2",
                "disability": "Disability", "gem": "GEM", "fsm": "Free School Meals",
                "male": "Male", "tundra_q1": "Tundra Q1", "tundra_q2": "Tundra Q2"}


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0.0  # suppressed or not applicable


def read_counts(path, year):
    """{ukprn: {characteristic: {attribute: ug_count}}} for the chosen base year."""
    data = defaultdict(lambda: defaultdict(dict))
    years = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = csv.DictReader(f)
        missing = {"UKPRN", "COHORT", "CHARACTERISTIC", "ATTRIBUTE", *UG_COLS} - set(rows.fieldnames or [])
        if missing:
            sys.exit(f"The file is missing expected columns: {sorted(missing)}")
        for r in rows:
            if r["COHORT"] != "All students" or r["CHARACTERISTIC"] not in CHARS:
                continue
            y = r.get("BASE_YEAR", "")
            years.add(y)
            data[(y, r["UKPRN"].strip())][r["CHARACTERISTIC"]][r["ATTRIBUTE"]] = sum(num(r[c]) for c in UG_COLS)
    year = year or max(years)
    print(f"Base years in file: {sorted(years)}; using {year}")
    return {uk: chars for (y, uk), chars in data.items() if y == year}


def profile(chars):
    out = {}
    for col, char, pick, drop_unknown in SPEC:
        attrs = chars.get(char, {})
        denom = sum(v for a, v in attrs.items() if not (drop_unknown and unknown(a)))
        out[col] = sum(v for a, v in attrs.items() if pick(a)) / denom if denom else None
    return out


def read_totals(path):
    """UG totals for 2024-25 from the OfS student numbers file (latest COUNT_ column)."""
    tot = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = csv.DictReader(f)
        col = sorted(c for c in rows.fieldnames if c.startswith("COUNT_2"))[-1]
        print(f"Undergraduate totals taken from {col}")
        for r in rows:
            if r["COHORT"] == "All students" and r["LEVEL_OF_STUDY"] == "All undergraduates":
                tot[r["UKPRN"].strip()][r["TYPE_OF_PROVISION"]] = int(num(r[col]))
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("size_and_shape_csv")
    ap.add_argument("--numbers", help="OfS student numbers file, for the undergraduate totals")
    ap.add_argument("--year", help="BASE_YEAR to use (default: latest in the file)")
    args = ap.parse_args()
    src = Path(args.size_and_shape_csv)
    counts = read_counts(src, args.year)
    totals = read_totals(args.numbers) if args.numbers else {}

    cols = [c for c, *_ in SPEC]
    tot_cols = ["Total FT UG", "Total PT UG", "Total Apprenticeship", "Total UG students"] if totals else []
    results = {}
    with open(src.with_name("student_profiles.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["UKPRN", *cols, *tot_cols])
        for uk in sorted(counts):
            p = profile(counts[uk])
            t = totals.get(uk, {})
            tt = [t.get("Full-time", 0), t.get("Part-time", 0), t.get("Apprenticeship", 0)]
            results[uk] = (p, sum(tt) if t else None)
            w.writerow([uk, *("" if p[c] is None else round(p[c], 6) for c in cols),
                        *((tt + [sum(tt)]) if totals else [])])

    lines = ["-- Student profiles from the OfS size and shape data, for public.site_providers",
             "UPDATE public.site_providers s SET profile = v.profile::jsonb,",
             "  ug_students = COALESCE(v.ug, s.ug_students), updated_at = now()",
             "FROM (VALUES"]
    vals = []
    for uk, (p, ug) in results.items():
        site = {k: (None if p[c] is None else round(p[c] * 100, 2)) for k, c in SITE_PROFILE.items()}
        vals.append(f"  ('{uk}', '{json.dumps(site)}', {ug if ug else 'NULL'}::int)")
    lines += [",\n".join(vals), ") v(ukprn, profile, ug)", "WHERE s.ukprn = v.ukprn;"]
    src.with_name("student_profiles_supabase.sql").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(results)} providers written to student_profiles.csv and student_profiles_supabase.sql")


if __name__ == "__main__":
    main()
