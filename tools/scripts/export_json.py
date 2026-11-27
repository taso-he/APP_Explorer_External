import gspread
import json
import os
import re
import time
import urllib.parse
import urllib.request
from google.oauth2.service_account import Credentials

# The Google service-account key, kept in your Windows user folder
# (e.g. C:\Users\<you>\credentials.json). Never put it in the repository.
CREDENTIALS_FILE = os.path.join(os.path.expanduser("~"), "credentials.json")
SHEET_ID = "1jH2blZLjztpLqAgh7BV7G-Kl7TI1_PZZxojEY2lH5Zg"
# Write data.json next to this script, so it always lands in the repo folder
# regardless of where the repo is cloned.
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

# ── Proposed regional access partnerships (RAPs) ─────────────────────────────
# Each RAP is defined by the local authority areas it covers (from the
# "Regional access partnership proposals" spreadsheet). An institution's RAP is
# found from the local authority of its postcode (postcodes.io admin_district,
# then admin_county for two-tier areas), so new institutions map automatically.
RAP_AREAS = {
    'East Anglia': [
        'Cambridgeshire', 'Essex', 'Norfolk', 'Peterborough',
        'Southend-on-sea', 'Suffolk', 'Thurrock',
    ],
    'East Midlands': [
        'Derby City', 'Derbyshire', 'Leicester City', 'Leicestershire',
        'Nottingham City', 'Nottinghamshire', 'Rutland',
    ],
    'East and North Yorkshire and Lincolnshire': [
        'East Riding of Yorkshire', 'Hull', 'Lincolnshire',
        'North East Lincolnshire', 'North Lincolnshire', 'North Yorkshire',
        'York',
    ],
    'Greater Manchester': [
        'Bolton', 'Bury', 'Manchester', 'Oldham', 'Rochdale', 'Salford',
        'Stockport', 'Tameside', 'Trafford', 'Wigan',
    ],
    'Lancashire and Cumbria': [
        'Blackburn with Darwen', 'Blackpool', 'Cumberland', 'Lancashire',
        'West Lancashire', 'Westmorland and Furness',
    ],
    'London': [
        'Barking and Dagenham', 'Barnet', 'Bexley', 'Brent', 'Bromley',
        'Camden', 'City of London', 'Croydon', 'Ealing', 'Enfield',
        'Greenwich', 'Hackney', 'Hammersmith & Fulham', 'Haringey', 'Harrow',
        'Havering', 'Hillingdon', 'Hounslow', 'Islington',
        'Kensington and Chelsea', 'Kingston upon Thames', 'Lambeth',
        'Lewisham', 'Merton', 'Newham', 'Redbridge', 'Richmond upon Thames',
        'Southwark', 'Sutton', 'Tower Hamlets', 'Waltham Forest', 'Wandsworth',
        'Westminster',
    ],
    'Merseyside': [
        'Halton', 'Knowsley', 'Liverpool', 'Sefton', 'St Helens', 'Wirral',
    ],
    'North East': [
        'County Durham', 'Darlington', 'Gateshead', 'Hartlepool',
        'Middlesbrough', 'Newcastle upon Tyne', 'North Tyneside',
        'Northumberland', 'Redcar and Cleveland', 'South Tyneside',
        'Stockton-on-Tees', 'Sunderland',
    ],
    'North West Midlands': [
        'Cheshire East', 'Cheshire West and Chester', 'Shropshire',
        'Staffordshire', 'Stoke-on-Trent', 'Telford and Wrekin', 'Warrington',
    ],
    'South Central': [
        'Bournemouth, Christchurch and Poole', 'Dorset', 'Hampshire',
        'Isle of Wight', 'Portsmouth', 'Southampton',
    ],
    'South East': [
        'Brighton & Hove', 'East Sussex', 'Kent', 'Medway', 'Surrey',
        'West Sussex',
    ],
    'South Midlands and Thames Valley': [
        'Bedford', 'Bracknell Forest', 'Buckinghamshire',
        'Central Bedfordshire', 'County of Hertfordshire', 'Luton',
        'Milton Keynes', 'North Northamptonshire', 'Oxfordshire', 'Reading',
        'Slough', 'Swindon', 'West Berkshire', 'West Northamptonshire',
        'Windsor and Maidenhead', 'Wokingham',
    ],
    'South West': [
        'Cornwall', 'Devon', 'Isles of Scilly', 'Plymouth', 'Somerset',
        'Torbay',
    ],
    'South Yorkshire': [
        'Barnsley', 'Doncaster', 'Rotherham', 'Sheffield',
    ],
    'West of England': [
        'Bath and North East Somerset', 'Bristol', 'Gloucestershire',
        'North Somerset', 'South Gloucestershire', 'Wiltshire',
    ],
    'West Midlands': [
        'Birmingham', 'Coventry', 'Dudley', 'Herefordshire', 'Sandwell',
        'Solihull', 'Walsall', 'Warwickshire', 'Wolverhampton',
        'Worcestershire',
    ],
    'West Yorkshire': [
        'Bradford', 'Calderdale', 'Kirklees', 'Leeds', 'Wakefield',
    ],
}


def _la_key(name):
    s = (name or "").lower().strip().replace("&", "and")
    s = re.sub(r"^(county of|city of) ", "", s)
    s = re.sub(r", (city|county) of$", "", s)
    s = re.sub(r" city$", "", s)
    s = s.replace("kingston upon hull", "hull")
    return re.sub(r"[^a-z]", "", s)

LA_TO_RAP = {_la_key(la): rap for rap, las in RAP_AREAS.items() for la in las}

def rap_for(district, county):
    for name in (district, county):
        rap = LA_TO_RAP.get(_la_key(name)) if name else None
        if rap:
            return rap
    return ""

def get_sheets_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)

def parse_num(val):
    if val is None or val == '':
        return None
    try:
        return float(str(val).replace('%','').strip())
    except:
        return None

def parse_int(val):
    if val is None or val == '':
        return None
    try:
        return int(float(str(val).strip()))
    except:
        return None

def _get_json(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _lookup_retired_postcode(pc):
    """A postcode that has been retired is missing from the main lookup. Use its
    last known coordinates, then the nearest live postcode for its local
    authority, so the institution still gets a map dot and a RAP."""
    try:
        q = urllib.parse.quote(pc)
        old = _get_json(f"https://api.postcodes.io/terminated_postcodes/{q}").get("result")
        if not old:
            return None
        near = _get_json(
            f"https://api.postcodes.io/postcodes?lon={old['longitude']}&lat={old['latitude']}&limit=1&radius=2000"
        ).get("result") or []
        res = dict(near[0]) if near else {}
        res["latitude"], res["longitude"] = old["latitude"], old["longitude"]
        print(f"  {pc} is a retired postcode - placed using its last known location.")
        return res
    except Exception:
        return None

def geocode_postcodes(inst_by_ukprn):
    """Fill in lat/lng and RAP on each institution from its postcode, using the free
    postcodes.io bulk endpoint (no API key). Institutions without a postcode,
    or whose postcode cannot be found, are left without coordinates."""
    # Unique, cleaned postcodes
    pc_to_insts = {}
    for uk, inst in inst_by_ukprn.items():
        pc = (inst.get("postcode") or "").strip().upper()
        if pc:
            pc_to_insts.setdefault(pc, []).append(inst)
    postcodes = list(pc_to_insts.keys())
    if not postcodes:
        print("  No postcodes to geocode.")
        return
    print(f"Geocoding {len(postcodes)} unique postcodes via postcodes.io...")
    found = 0
    for i in range(0, len(postcodes), 100):
        batch = postcodes[i:i + 100]
        body = json.dumps({"postcodes": batch}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.postcodes.io/postcodes",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  Geocode batch {i//100 + 1} failed: {e}")
            time.sleep(1)
            continue
        for item in data.get("result", []):
            res = item.get("result")
            query = (item.get("query") or "").strip().upper()
            if not res:
                res = _lookup_retired_postcode(query)
            if res and res.get("latitude") is not None:
                rap = rap_for(res.get("admin_district"), res.get("admin_county"))
                for inst in pc_to_insts.get(query, []):
                    inst["lat"] = round(res["latitude"], 5)
                    inst["lng"] = round(res["longitude"], 5)
                    inst["rap"] = rap
                if not rap:
                    print(f"  Note: no RAP found for {query} ({res.get('admin_district')}) - add its area to RAP_AREAS.")
                found += 1
        print(f"  ...geocoded {min(i + 100, len(postcodes))}/{len(postcodes)}")
        time.sleep(0.3)  # be gentle with the free service
    print(f"  Matched coordinates for {found} of {len(postcodes)} postcodes.")


# ── Intersection targets ────────────────────────────────────────────────────
# A target filed under "Intersection of characteristics" (e.g. young students
# with vocational qualifications) should also turn up under each separate
# characteristic it combines (Age, Entry qualifications). Each one gets an
# `also_characteristics` list, which the site uses alongside `characteristic`.
# An optional `intersection_components` column in the Targets tab (labels
# separated by ";") overrides the keyword rules for that row.
INTERSECTION_LABEL = 'Intersection of characteristics'
INTERSECTION_RULES = [
    ('Age', r'\b(young|mature|under[ -]?2[15]|u2[15]|aged? \d+|21[-–]25|over[ -]?21|age)\b'),
    ('Entry qualifications', r'(vocational|btec|technical qualif|level 3 qualif|entry qualif|non[- ]a[- ]?level|access to he|a[- ]level)'),
    ('Eligibility for Free School Meals (FSM)', r'\b(fsm|free school meals?)\b'),
    ('Deprivation (Index of Multiple Deprivations [IMD])', r'(\bimd\s?q?\s?[1-5]|\bimd\b|deprivation|deprived|\bimdq)'),
    ('Ethnicity', r'\b(black|asian|ethnic\w*|global majority|bame|bme|white|mixed|gypsy|roma|travellers?|specified ethnicities)\b'),
    ('Sex', r'\b(males?|females?|men|women|sex|gender|boys|girls)\b'),
    ('Disability', r'\b(disab|disabled|mental health)'),
    ('Care experienced', r'\b(care[- ]experienced|care leavers?)\b'),
    ('Low Participation Neighbourhood (LPN)', r'(\bpolar\s?4?|\blpn\b|low participation|\bpq\s?[1-5])'),
    ('Tracking Underrepresentation by Area (TUNDRA)', r'\btundra\b'),
    ('Low income background', r'\blow[- ]income\b'),
]
# Words inside labels like "Intersection of characteristics (Ethnicity and Sex)"
INTERSECTION_LABEL_HINTS = {
    'ethnicity': 'Ethnicity',
    'deprivation': 'Deprivation (Index of Multiple Deprivations [IMD])',
    'imd': 'Deprivation (Index of Multiple Deprivations [IMD])',
    'sex': 'Sex',
}


def tag_intersection(obj, override=''):
    """Set `also_characteristics` on an intersection target and tidy its label."""
    ch = obj.get('characteristic', '')
    if 'intersection' not in ch.lower():
        return
    if override.strip():
        found = [p.strip() for p in override.split(';') if p.strip()]
    else:
        found = []
        m = re.search(r'\((.*)\)', ch)
        if m:
            for word in re.split(r'\band\b|,', m.group(1).lower()):
                for hint, label in INTERSECTION_LABEL_HINTS.items():
                    if hint in word and label not in found:
                        found.append(label)
        text = ' '.join(obj.get(k, '') for k in ('target_group', 'comparator_group', 'aim')).lower()
        for label, pattern in INTERSECTION_RULES:
            if label not in found and re.search(pattern, text):
                found.append(label)
        # "male and female" covers both sexes, so it isn't a Sex target
        if 'Sex' in found and re.search(r'\b(males? and females?|females? and males?)\b', text) \
                and not re.search(r'\b(sex|gender)\b', ch.lower()):
            found.remove('Sex')
    # Fold "Intersection of characteristics (Ethnicity and Sex)" etc. into one
    # category - the components now live in also_characteristics.
    obj['characteristic'] = INTERSECTION_LABEL
    obj['also_characteristics'] = found


def main():
    print("Connecting to Google Sheets...")
    gc = get_sheets_client()
    ss = gc.open_by_key(SHEET_ID)

    # ── APPs tab ──────────────────────────────────────────────────────────
    print("Reading APPs tab...")
    register = ss.worksheet("APPs")
    r_rows = register.get_all_values()
    url_by_ukprn = {}
    past_url_by_ukprn = {}
    for row in r_rows[1:]:
        ukprn    = row[0].strip() if len(row) > 0 else ''
        url      = row[3].strip() if len(row) > 3 else ''
        past_url = row[4].strip() if len(row) > 4 else ''
        if ukprn and url.startswith('http'):
            url_by_ukprn[ukprn] = url
        if ukprn and past_url.startswith('http'):
            past_url_by_ukprn[ukprn] = past_url

    # ── Institutions tab ──────────────────────────────────────────────────
    print("Reading Institutions tab...")
    inst_sheet = ss.worksheet("Institutions")
    i_rows = inst_sheet.get_all_values()

    # Find the postcode column by header name (robust to where it is added, as
    # long as it is appended to the right of the existing positional columns).
    header_row = i_rows[0] if i_rows else []
    pc_col = -1
    for idx, h in enumerate(header_row):
        if 'postcode' in h.strip().lower():
            pc_col = idx
            break
    if pc_col == -1:
        print("  Note: no 'postcode' column found in Institutions tab - map coordinates will be skipped.")
    else:
        print(f"  Found postcode column at index {pc_col} ('{header_row[pc_col]}')")
    # A third mission group (for providers in three groups) is appended on the right, so it is
    # also found by header name
    mg3_col = next((i for i, h in enumerate(header_row) if h.strip().lower() in ('mission group 3', 'mission_group3')), -1)

    inst_by_ukprn = {}
    for row in i_rows[1:]:
        def g(idx):
            return row[idx].strip() if idx < len(row) else ''
        ukprn = g(0)
        if not ukprn:
            continue
        inst_by_ukprn[ukprn] = {
            "postcode":       g(pc_col) if pc_col != -1 else '',
            "mission_group":  g(2),
            "mission_group2": g(3),
            "mission_group3": g(mg3_col) if mg3_col != -1 else '',
            "region":         g(4),
            "mature_pct":     parse_num(g(5)),
            "imd_q1":         parse_num(g(6)),
            "imd_q2":         parse_num(g(7)),
            "imd_q3":         parse_num(g(8)),
            "imd_q4":         parse_num(g(9)),
            "imd_q5":         parse_num(g(10)),
            "disability":     parse_num(g(11)),
            "asian":          parse_num(g(12)),
            "black":          parse_num(g(13)),
            "mixed":          parse_num(g(14)),
            "other_eth":      parse_num(g(15)),
            "white":          parse_num(g(16)),
            "gem":            parse_num(g(17)),
            "fsm":            parse_num(g(18)),
            "uk_pct":         parse_num(g(19)),
            "alevel":         parse_num(g(20)),
            "btec":           parse_num(g(21)),
            "access_found":   parse_num(g(22)),
            "male":           parse_num(g(23)),
            "lgb":            parse_num(g(24)),
            "tundra_q1":      parse_num(g(25)),
            "tundra_q2":      parse_num(g(26)),
            "tundra_q3":      parse_num(g(27)),
            "tundra_q4":      parse_num(g(28)),
            "tundra_q5":      parse_num(g(29)),
            # Student numbers (cols 30-33)
            "total_ft_ug":          parse_int(g(30)),
            "total_pt_ug":          parse_int(g(31)),
            "total_apprenticeship": parse_int(g(32)),
            "total_ug_students":    parse_int(g(33)),
        }

    # ── Geocode postcodes -> lat/lng via postcodes.io (free, no API key) ────
    if pc_col != -1:
        geocode_postcodes(inst_by_ukprn)

    # ── Targets tab ───────────────────────────────────────────────────────
    print("Reading Targets tab...")
    targets = ss.worksheet("Targets")
    t_rows = targets.get_all_values()
    headers = [h.lower().replace(' ','_').replace('?','').replace('/','_')
                .replace('(','').replace(')','').strip()
               for h in t_rows[0]]

    vague = {
        'other',
        'other (please specify in description)',
        'not specified (please give detail in description)',
        'not specified',
        # Blank in the plan: show the cleaned value where there is one
        'not stated',
        'n/a',
        '',
    }

    def prefer_clean(original, clean):
        if original.strip().lower() in vague and clean.strip():
            return clean.strip()
        return original.strip()

    def find_col(name):
        try:
            return headers.index(name)
        except ValueError:
            return -1

    idx_char_clean = find_col('characteristic_clean')
    idx_tg_clean   = find_col('target_group_clean')
    idx_cg_clean   = find_col('comparator_group_clean')
    idx_intersect  = find_col('intersection_components')

    def safe(row, idx):
        return row[idx].strip() if idx != -1 and idx < len(row) else ''

    output  = []
    skipped = 0

    for row in t_rows[1:]:
        def g(idx):
            return row[idx].strip() if idx < len(row) else ''

        obj = {}
        for i, h in enumerate(headers):
            obj[h] = row[i].strip() if i < len(row) else ''

        ukprn = obj.get('ukprn', '').strip()

        if not obj.get('reference_number', '').strip():
            skipped += 1
            continue

        obj['characteristic']   = prefer_clean(obj.get('characteristic', ''),   safe(row, idx_char_clean))
        obj['target_group']     = prefer_clean(obj.get('target_group', ''),     safe(row, idx_tg_clean))
        obj['comparator_group'] = prefer_clean(obj.get('comparator_group', ''), safe(row, idx_cg_clean))
        tag_intersection(obj, safe(row, idx_intersect))
        obj.pop('intersection_components', None)

        obj['plan_url']      = url_by_ukprn.get(ukprn, '')
        obj['past_plan_url'] = past_url_by_ukprn.get(ukprn, '')
        obj['current_plan']  = obj.get('current_plan', '').strip()
        inst = inst_by_ukprn.get(ukprn, {})
        for k, v in inst.items():
            obj[k] = v

        output.append(obj)

    print(f"Processed {len(output)} targets ({skipped} rows skipped)")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    print(f"Written to {OUTPUT_FILE}")
    size_kb = len(json.dumps(output)) / 1024
    print(f"File size: {size_kb:.0f} KB")

if __name__ == "__main__":
    main()