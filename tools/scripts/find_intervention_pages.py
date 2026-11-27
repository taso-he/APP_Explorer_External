"""
Check the page number of each extracted intervention against the plan's PDF text.

The model often gets an activity's page wrong by one or two, because it counts
printed page numbers or the end of the previous row. This script looks for the
activity's name (and, failing that, the start of its description) in the text of
each PDF page, and takes the page nearest the model's answer where it's found.
It needs no AI and costs nothing to run.

Two ways to use it:

  1. Inside the extraction tool, after the model returns its records:
       from find_intervention_pages import check_page, read_pdf_pages
       pages = read_pdf_pages("plan.pdf")
       page, source = check_page(pages, record["intervention_name"],
                                 record["intervention_description"], record["page"])

  2. On an export, from the command line:
       python find_intervention_pages.py export.csv --pdfs plan_pdfs --out export_pages_checked.csv
     The PDFs folder holds one file per provider, named by UKPRN (e.g. 10007161.pdf).
     The output is the same CSV with three added columns: page_checked, page_source
     and page_note.

page_source is one of:
  name          found by the activity's name (the most reliable)
  description   found by the start of its description
  model         not found in the text; the model's page is kept, and page_note says so

Needs: pip install pypdf
"""

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("A library is missing. Run: pip install pypdf")

# How far from the model's page a match may be. Activity names also appear in
# contents pages, evaluation tables and annexes; a limit keeps those out.
MAX_DISTANCE = 3

STATUS_LABEL = re.compile(r"\((new|ongoing|existing|extension|extended)[^)]*\)", re.I)


def squash(text):
    """Lower case, letters and digits only. PDF text breaks words and lines
    unpredictably inside tables, so spaces and punctuation are ignored."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = re.sub(r"(?<=[A-Za-z])020(?=[a-z])|\s013\s", " ", t)  # encoding faults in some extractions
    return re.sub(r"[^a-z0-9]", "", t.lower())


def read_pdf_pages(pdf_path):
    """The squashed text of every page; index 0 is PDF page 1."""
    return [squash(p.extract_text() or "") for p in PdfReader(str(pdf_path)).pages]


def snippets(text, sizes):
    """The first n words of the text, for each n, longest first."""
    words = STATUS_LABEL.sub(" ", str(text or "")).split()
    out = []
    for n in sizes:
        if len(words) >= min(n, 2):
            s = squash(" ".join(words[:n]))
            if len(s) >= 8 and s not in out:
                out.append(s)
    return out


def check_page(pages, name, description, model_page=None):
    """Return (page, source). pages comes from read_pdf_pages()."""
    try:
        model_page = int(model_page)
    except (TypeError, ValueError):
        model_page = None

    for source, candidates in (("name", snippets(name, (8, 6, 4, 3))),
                               ("description", snippets(description, (10, 7, 5)))):
        for snippet in candidates:
            found = [i + 1 for i, text in enumerate(pages) if snippet in text]
            if not found:
                continue
            if model_page is None:
                if len(found) == 1:
                    return found[0], source
                continue  # several matches and nothing to choose between them
            near = [p for p in found if abs(p - model_page) <= MAX_DISTANCE]
            if near:
                # Closest to the model's answer; on a tie, the earlier page (where the row starts)
                return min(near, key=lambda p: (abs(p - model_page), p)), source
    return model_page, "model"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", help="extraction export (CSV)")
    ap.add_argument("--pdfs", required=True, help="folder of plan PDFs named by UKPRN")
    ap.add_argument("--out", help="output CSV (default: <export>_pages_checked.csv)")
    args = ap.parse_args()

    with open(args.export, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames + ["page_checked", "page_source", "page_note"]
        rows = list(reader)

    cache, changed, kept = {}, 0, 0
    for r in rows:
        ukprn = str(r.get("ukprn", "")).strip()
        pdf = Path(args.pdfs) / f"{ukprn}.pdf"
        if ukprn not in cache:
            cache[ukprn] = read_pdf_pages(pdf) if pdf.exists() else None
        pages = cache[ukprn]
        if pages is None:
            r.update(page_checked=r.get("page", ""), page_source="model",
                     page_note=f"No PDF found at {pdf}")
            kept += 1
            continue
        page, source = check_page(pages, r.get("intervention_name"), r.get("intervention_description"), r.get("page"))
        r["page_checked"] = "" if page is None else page
        r["page_source"] = source
        if source == "model":
            r["page_note"] = "Name and description not found near this page: check by hand"
            kept += 1
        elif str(page) != str(r.get("page", "")).strip():
            r["page_note"] = f"Changed from {r.get('page')}"
            changed += 1
        else:
            r["page_note"] = ""

    out = args.out or str(Path(args.export).with_name(Path(args.export).stem + "_pages_checked.csv"))
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} records: {changed} pages changed, {kept} not found (model's page kept), "
          f"{len(rows) - changed - kept} confirmed. Saved to {out}")


if __name__ == "__main__":
    main()
