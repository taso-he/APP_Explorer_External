"""
Targeted re-run of the Claude reviewer on the review-queue items Claude was unsure about.

Most of the open "field" items in qa_person_checks are there because the first review only
saw a window of pages (it missed the objectives, the risk mapping or an annex). This script
sends each provider's WHOLE plan, with the current values of the records that still have
open field items, and asks Claude only about those fields.

On --collect, Python checks every quote against the PDF (as the main review does). Then:
  - "Correct" (the value stands)        -> the item is closed as kept (status rejected)
  - a correction with a verified quote  -> the value is applied to interventions_working
                                           and the item is closed (status accepted)
  - anything else (Unsure, quote not found, image page, bad codes) -> stays open, with
                                           Claude's new reasoning added to its note
Nothing is written to Supabase unless you add --apply. Without it, collect only saves a CSV
of what it would do, so you can look first. --apply closes the "value stands" items and puts each
verified correction into its item as the suggested value (with Claude's quote), so you accept it
with one click in the review page; the data itself is not changed. --apply-corrections instead
writes the corrections straight into interventions_working and closes those items too.

Ways to run it (Windows, from the repository folder):
  1. Free estimate:   python taso-handover\\scripts\\recheck_open_claude.py --estimate
  2. Send the batch:  python taso-handover\\scripts\\recheck_open_claude.py --batch
  3. Look first:      python taso-handover\\scripts\\recheck_open_claude.py --collect RUN_ID
  4. Apply:           python taso-handover\\scripts\\recheck_open_claude.py --collect RUN_ID --apply

Options: --ukprn LIST, --model, --effort (default high), --pdfs, --out, --dry-run (offline estimate)
Keys: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY (environment variables, never in this file)
"""
import argparse
import base64
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_interventions_claude as R  # noqa: E402
from pypdf import PdfReader  # noqa: E402

PROMPT_VERSION = "claude-recheck-v1"
SKIP_RUNS = {"missing-records-2026-11-20"}  # new records drafted by hand: need a person, not Claude

SCHEMA = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "string"},
                    "fields": {"type": "array", "items": R.RESPONSE_SCHEMA["properties"]["records"]["items"]
                               ["properties"]["fields"]["items"]},
                },
                "required": ["record_id", "fields"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["records"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You are re-checking fields of records produced by an automated extraction of interventions
from an English higher education provider's Access and Participation Plan. An earlier check could not
decide these fields, usually because it was only sent some of the plan's pages. You now have the WHOLE
plan: use the objectives, the risk mapping tables, the targets and any annexes wherever they are.

How to answer:
- One entry in "records" for every record_id given, and in "fields" one entry for each field listed
  under "fields_to_check" for that record (no others).
- The earlier check's suggestion and reason are given for context only. Judge against the plan.
- status "Correct" if the current value is right: corrected_value, evidence_quote and error_type are
  empty strings, evidence_page 0.
- Any other status: give the corrected value in the same format as the current value (JSON lists stay
  JSON lists; demographics_combined is True or False; page is a number), an evidence_quote of up to 30
  words copied exactly from the plan, and evidence_page as the page number of the PDF.
- Use "Unsure" only if the whole plan still doesn't settle it, and say why in evidence_quote.
- Providers often number risks their own way and map them to the EORR elsewhere in the plan: follow
  that mapping. Write risks as "EORR Risk N – name".
- Judge only against the plan. Do not improve the provider's wording.

QA RULES
"""


# ---------- Supabase ----------

def sb_request(method, path, body=None, prefer="return=representation"):
    url, key = R.supabase_settings()
    headers = {"apikey": key, "Content-Type": "application/json", "Prefer": prefer}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/{path}", method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"Supabase error {e.code} on {path}: {e.read().decode('utf-8', 'replace')}")


def fetch_all(path):
    rows, start = [], 0
    while True:
        page = sb_request("GET", f"{path}&limit=1000&offset={start}")
        rows += page
        if len(page) < 1000:
            return rows
        start += 1000


def load_open():
    checks = fetch_all("qa_person_checks?select=*&kind=eq.field&status=eq.open&order=check_id")
    checks = [c for c in checks if c.get("review_run_id") not in SKIP_RUNS and c.get("field") in R.FIELDS]
    ids = sorted({c["record_id"] for c in checks})
    records = {}
    for i in range(0, len(ids), 100):
        q = ",".join(f'"{x}"' for x in ids[i:i + 100])
        for r in fetch_all(f"interventions_working?select=*&removed=eq.false&record_id=in.({urllib.parse.quote(q)})"):
            records[r["record_id"]] = r
    checks = [c for c in checks if c["record_id"] in records]
    return checks, records


# ---------- requests ----------

def as_text(v):
    if v is None:
        return ""
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def build(checks, records, pdf_dir):
    by_provider = defaultdict(list)
    for c in checks:
        by_provider[str(c["ukprn"]).strip()].append(c)
    aims = R.load_targets()
    requests = []
    for ukprn, cs in sorted(by_provider.items()):
        provider = cs[0]["provider"]
        pdf_path = R.get_pdf(ukprn, "", pdf_dir)
        n_pages = len(PdfReader(str(pdf_path)).pages)
        by_record = defaultdict(list)
        for c in cs:
            by_record[c["record_id"]].append(c)
        recs = []
        for rid, items in by_record.items():
            r = records[rid]
            recs.append({
                "record_id": rid,
                "current_values": {f: as_text(r.get(f)) for f in R.FIELDS},
                "fields_to_check": [{"field": c["field"], "earlier_suggestion": c.get("suggested_value") or "",
                                     "earlier_reason": c.get("reason") or "",
                                     "earlier_quote": c.get("evidence_quote") or ""} for c in items],
            })
        target_list = "\n".join(f"{ref}: {aim}" for ref, aim in sorted(aims.get(ukprn, {}).items()))
        text = (f"Provider: {provider} (UKPRN {ukprn})\nThe attached PDF is the whole plan ({n_pages} pages).\n\n"
                f"The provider's current-plan targets (reference: aim):\n{target_list or '(none found)'}\n\n"
                f"Records to re-check:\n{json.dumps(recs, ensure_ascii=False, indent=1)}")
        data = base64.standard_b64encode(pdf_path.read_bytes()).decode("ascii")
        requests.append({"ukprn": ukprn, "provider": provider, "pages": n_pages,
                         "check_ids": [c["check_id"] for c in cs],
                         "content": [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                                     "data": data}},
                                     {"type": "text", "text": text}]})
    return requests


def body(model, effort, system, content):
    b = R.request_body(model, effort, system, content)
    b["output_config"]["format"]["schema"] = SCHEMA
    return b


def system(rules):
    return [{"type": "text", "text": INSTRUCTIONS + rules, "cache_control": {"type": "ephemeral"}}]


# ---------- deciding ----------

def decide(check, record, entry, texts):
    """Returns (action, value, note): action is keep, apply or open."""
    if entry is None:
        return "open", None, "Re-check: no answer for this field"
    status, found = R.check_field(entry, texts)
    current = as_text(record.get(check["field"]))
    value = entry.get("corrected_value", "")
    why = (entry.get("evidence_quote") or "").strip()
    page = entry.get("evidence_page") or ""
    if status == "Correct" or (status != "Unsure" and R.same_value(current, value)):
        return "keep", current, "Claude re-check with the whole plan: the value stands"
    if status == "Unsure" or found is not True or not value:
        reason = "still unsure" if entry["status"] == "Unsure" else (
            "quote on an image page" if found == "image" else "its quote or codes did not check out")
        return "open", value or None, f"Claude re-check ({reason}): {why[:300]}" + (f" (p{page})" if page else "")
    return "apply", value, f"Claude re-check with the whole plan, quote verified on p{page}: \"{why[:200]}\""


def collect(args):
    out_dir = Path(args.out)
    manifest = json.loads((out_dir / f"{args.collect}_recheck.json").read_text(encoding="utf-8"))
    results, waiting = {}, False
    for batch_id in manifest["batch_ids"]:
        with R.api_get(f"{R.API_URL}/messages/batches/{batch_id}") as resp:
            batch = json.loads(resp.read())
        print(f"Batch {batch_id}: {batch['processing_status']} {batch.get('request_counts', {})}")
        if batch["processing_status"] != "ended":
            waiting = True
            continue
        with R.api_get(batch["results_url"]) as resp:
            for line in resp:
                if line.strip():
                    item = json.loads(line)
                    results[item["custom_id"]] = item["result"]
    if waiting:
        sys.exit("Not finished yet. Nothing has been changed: try --collect again later.")
    checks, records = load_open()
    by_check = {c["check_id"]: c for c in checks}
    pdf_dir = Path(manifest["pdfs"])
    decisions, totals = [], {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    for meta in manifest["requests"]:
        msg = R.batch_message(results.get(meta["custom_id"], {"type": "missing"}))
        R.add_usage(totals, msg["usage"])
        try:
            answer = json.loads(msg["text"]) if msg["stop_reason"] not in ("refusal", "max_tokens", "error") else {}
        except json.JSONDecodeError:
            answer = {}
        got = {(r["record_id"], f["field"]): f for r in answer.get("records", []) for f in r.get("fields", [])}
        texts = [pg.extract_text() or "" for pg in PdfReader(str(pdf_dir / f"{meta['ukprn']}.pdf")).pages]
        for cid in meta["check_ids"]:
            c = by_check.get(cid)
            if not c:
                continue  # decided by someone since the batch was sent
            action, value, note = decide(c, records[c["record_id"]], got.get((c["record_id"], c["field"])), texts)
            decisions.append({"check_id": cid, "provider": c["provider"], "record_id": c["record_id"],
                              "field": c["field"], "action": action, "current_value": as_text(records[c["record_id"]].get(c["field"])),
                              "new_value": value or "", "note": note,
                              "quote": (got.get((c["record_id"], c["field"])) or {}).get("evidence_quote", ""),
                              "page": (got.get((c["record_id"], c["field"])) or {}).get("evidence_page") or ""})
    path = out_dir / f"{args.collect}_decisions.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(decisions[0]) if decisions else ["check_id"])
        w.writeheader()
        w.writerows(decisions)
    counts = defaultdict(int)
    for d in decisions:
        counts[d["action"]] += 1
    print(f"\n{len(decisions)} items: {counts['keep']} value stands, {counts['apply']} corrected, "
          f"{counts['open']} left open for a person. Saved {path}")
    print(f"Cost about ${R.cost(totals, manifest['model']) * 0.5:.2f} (batch price)")
    if args.apply_corrections:
        args.apply = True
    if not args.apply:
        print("Nothing changed in Supabase. Look at the CSV, then run again with --apply.")
        return
    now = datetime.now(timezone.utc).isoformat()
    for d in decisions:
        cid = urllib.parse.quote(d["check_id"])
        if d["action"] == "open":
            old = by_check[d["check_id"]].get("note") or ""
            sb_request("PATCH", f"qa_person_checks?check_id=eq.{cid}&status=eq.open",
                       {"note": (old + "\n" if old else "") + d["note"]}, prefer="return=minimal")
            continue
        if d["action"] == "apply" and not args.apply_corrections:
            sb_request("PATCH", f"qa_person_checks?check_id=eq.{cid}&status=eq.open",
                       {"suggested_value": d["new_value"], "evidence_quote": d["quote"] or None,
                        "evidence_page": int(d["page"]) if d["page"] else None,
                        "note": "Claude re-check with the whole plan suggests this value (quote verified on the page)"},
                       prefer="return=minimal")
            continue
        if d["action"] == "apply":
            rid = urllib.parse.quote(d["record_id"])
            sb_request("PATCH", f"interventions_working?record_id=eq.{rid}",
                       {d["field"]: d["new_value"], "updated_at": now, "updated_by": "claude-recheck"},
                       prefer="return=minimal")
        sb_request("PATCH", f"qa_person_checks?check_id=eq.{cid}&status=eq.open",
                   {"status": "accepted" if d["action"] == "apply" else "rejected", "final_value": d["new_value"],
                    "suggested_value": d["new_value"] if d["action"] == "apply" else None,
                    "note": d["note"], "decided_by": "claude-recheck", "decided_at": now}, prefer="return=minimal")
    print("Applied to Supabase.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ukprn")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--pdfs", default=str(R.HERE / "plan_pdfs"))
    ap.add_argument("--out", default=str(R.HERE / "claude_review_results"))
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--collect", metavar="RUN_ID")
    ap.add_argument("--apply", action="store_true",
                    help="with --collect: close 'value stands' items and queue corrections as suggestions")
    ap.add_argument("--apply-corrections", action="store_true",
                    help="with --collect: write corrections straight into the data instead of queueing them")
    args = ap.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    if args.collect:
        return collect(args)
    if not (args.estimate or args.dry_run or args.batch):
        sys.exit("Choose --estimate, --dry-run or --batch (see --help).")

    checks, records = load_open()
    if args.ukprn:
        keep = {u.strip() for u in args.ukprn.split(",")}
        checks = [c for c in checks if str(c["ukprn"]).strip() in keep]
    if not checks:
        sys.exit("No open field items to re-check.")
    pdf_dir = Path(args.pdfs)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    rules = (R.DOCS / "interventions_qa_rules.md").read_text(encoding="utf-8")
    print(f"{len(checks)} open field items on {len({c['record_id'] for c in checks})} records, "
          f"{len({c['ukprn'] for c in checks})} providers. Preparing whole-plan requests...")
    requests = build(checks, records, pdf_dir)
    print(f"{len(requests)} requests, {sum(r['pages'] for r in requests)} PDF pages in total")

    p_in, p_out, p_write, p_read = R.PRICES.get(args.model, R.PRICES["claude-opus-5-5"])
    if args.estimate or args.dry_run:
        if args.dry_run:
            rules_tok = len(INSTRUCTIONS + rules) // 4
            in_tok = sum(r["pages"] * R.TOKENS_PER_PDF_PAGE + len(r["content"][1]["text"]) // 4 for r in requests)
        else:
            rules_tok = R.count_tokens(args.model, INSTRUCTIONS + rules)
            in_tok = sum(R.count_tokens(args.model, r["content"]) for r in requests)
        out_tok = len(checks) * 250 + len(requests) * R.THINKING_TOKENS_PER_REQUEST
        fixed = in_tok * p_in + rules_tok * (p_write + (len(requests) - 1) * p_read)
        low, high = (fixed + out_tok * 0.6 * p_out) / 1e6, (fixed + out_tok * 1.6 * p_out) / 1e6
        print(f"Input tokens: {in_tok:,} (+{rules_tok:,} rules, cached). Output about {out_tok:,}.")
        print(f"Estimated cost: ${low:.2f}-${high:.2f}; with --batch (half price): ${low / 2:.2f}-${high / 2:.2f}")
        return

    run_id = datetime.now(timezone.utc).strftime("recheck-%Y%m%d-%H%M%S")
    ids, chunk, size = [], [], 0
    def send():
        with R.api_post("/messages/batches", {"requests": chunk}) as resp:
            ids.append(json.loads(resp.read())["id"])
    for i, req in enumerate(requests):
        item = {"custom_id": f"req-{i:04d}", "params": body(args.model, args.effort, system(rules), req["content"])}
        n = len(json.dumps(item))
        if chunk and size + n > 150_000_000:
            send()
            chunk, size = [], 0
        chunk.append(item)
        size += n
    send()
    manifest = {"run_id": run_id, "model": args.model, "effort": args.effort, "prompt_version": PROMPT_VERSION,
                "pdfs": str(pdf_dir.resolve()), "batch_ids": ids,
                "requests": [{"custom_id": f"req-{i:04d}", "ukprn": r["ukprn"], "provider": r["provider"],
                              "check_ids": r["check_ids"]} for i, r in enumerate(requests)]}
    (Path(args.out) / f"{run_id}_recheck.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Sent {len(requests)} requests as {len(ids)} batch job(s). Run ID {run_id}. Collect later with:")
    print(f"  python taso-handover\\scripts\\recheck_open_claude.py --collect {run_id}")


if __name__ == "__main__":
    main()
