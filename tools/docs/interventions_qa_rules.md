# Interventions QA rules

These are the rules used in the manual QA (updated 22 Nov 2026 with the decisions made while clearing the review queue; 6 Nov 2026 with the decisions from the review of the first 67 plans; earlier, 28 Oct 2026 after comparing the Claude reviewer with the manual QA of The Northern School of Art) of the interventions extraction (Bishop Auckland, Middlesbrough, NCG, Durham, New College Durham and Northumbria). The automated reviewer should apply exactly these rules, so that its verdicts can be compared with the manual QA.

## Summary of judgement calls (to 22 Nov 2026)

The full rules for each field are below. These are the judgement calls that settled most disagreements in the review, in brief:

1. **One record per activity, not per table.** An activity that is a row in several strategy tables is one record listing each of those strategies. A strategy named only in a cross intervention column is never added. Duplicate records made one per table are merged into the first row.
2. **Only strategy-table rows are interventions.** Evaluation, data and monitoring rows are removed; financial support or services described only elsewhere in the plan are not interventions.
3. **Descriptions are the plan's own words from the Activity column.** No paraphrase, never Inputs or Outcomes text; blank when the row has nothing beyond its name.
4. **Students targeted come from the row first.** The row's text, its name or a student group column. The strategy's group or objectives are used only when the row names no group at all.
5. **Student group codes follow only what is stated.** No codes by inference (no `age` without an age group; IMD is `area_based` only). "Socio-economically disadvantaged" with no measure named is `other`. `all_students` is combined with specific codes only where provision is open to all but targets particular groups.
6. **Lifecycle stages come from the row and its strategy's targets.** Claude tended to add stages; a stage is added only where the row states it.
7. **Linked targets follow the row's outcomes.** Match the row's outcomes to the strategy's objectives, then to targets; leave out targets none of the outcomes relate to. Use an intervention matrix where the plan has one.
8. **Risks are recorded only where the plan names EORR risks.** By number or in the EORR's own words; providers' own risk numbers only through their own EORR mapping; risks linked to a student group apply to that group's strategy; near-EORR wording doesn't count.

## What counts as an intervention

- One record per row of an intervention strategy table, whatever the row is, except rows that are only research, evaluation or data work (see below). An activity that appears in the tables of two strategies (including a row such as "as explained in intervention 4" or "IST1; IST2 - As 4.5") is one record that lists both strategies, with the targets and risks of each (extraction prompt v4; confirmed by David, 22 Nov). This applies only where the activity is a row in each strategy's table; a strategy named only in the row's cross intervention column is not added (e.g. Activate Learning's "Enhancing Financial Support Awareness and Uptake" is a row in the IS1, IS2 and IS3 tables, so it lists those three, not IS4). Treat it as a Duplicate only if two records describe the same activity. Activity codes are sometimes reused for different activities in different strategies (e.g. Teesside's ISM6): these are separate records, and a missing one is reported as a missed intervention.
- "Links to IS3 and IS4" lines, and strategies named in a "Cross intervention" or "Strategy map" column ("This intervention will also relate to...", "IS2, IS3"), don't add strategies, targets or risks to a row. The row belongs only to the strategy whose activity table it is in.
- Rows that only describe running or evaluating the work (e.g. "Administration", "Evaluation") are Not an intervention, and are not missing records.
- Where a strategy shows its activities in a diagram with short labels and then describes each in its own paragraph, each labelled activity is a row; its name and description come from its paragraph. Keep a description taken from that paragraph (don't replace it with the diagram's label).
- Where the extraction made one record per table for an activity that appears in several strategy tables, keep one record (the first row, where the activity is first set out, with the fullest description from any of its rows), list every strategy whose table it is in, and remove the others as duplicates (e.g. LSBU's Personal Development Plan, Peer Assisted Learning and Action Learning; Imperial's Pre-arrival residential and Cohort Activities; David, 22 Nov).
- Rows that are only research, evaluation, data, dashboards, surveys, monitoring or reviews of the provider's own processes (e.g. LSBU's "Implementation and use of HEAT") are Not an intervention and are removed (David, 26 Nov; this replaces the earlier rule that kept research and monitoring rows). Rows that pair monitoring with support for students, research internships for students, staff training, working groups, governance and curriculum or assessment changes stay. Activities with pupils or students that also mention evaluating their impact stay (David, 22 Nov).
- Rows the extraction missed (missing records) are added unless they are research, evaluation, monitoring, tracking or data work (David, 20 Nov).
- Similar names are not the same activity ("Curriculum Design" and "Curriculum Intent"; "YSJ Scholarships" and "YSJ Scholarships Plus").
- Only rows of strategy activity tables are interventions. A bursary, scholarship, hardship fund, service or programme that is a row in a strategy table is an intervention; one described only elsewhere in the plan (for example NCG's financial support section or its Twilight counselling service) is Not an intervention (David, 29 Oct).

## Field rules

| Field | Rule |
| --- | --- |
| intervention_name | The activity's name as written in the table, word for word, including any subtitle. Status labels in brackets, such as "(New initiative)" or "(Extension to existing resource)", are left out of the name and recorded in activity_status (extraction prompt v4). |
| intervention_description | The text of the Activity (or Description) column for that row, word for word. Not the Inputs, Outcomes or Cross intervention columns. Small differences in spacing, punctuation, bullets and line breaks don't matter; dropped, added or changed words do. A summary or paraphrase of the row is wrong: use the plan's own words, including a lead-in label that is part of the text (e.g. "Staff and Faculty Development: Provide training..."). Where the row has no description beyond the activity's name, leave it empty: never fill it from the Inputs or Outcomes columns (David, 22 Nov). |
| intervention_strategy | The number and title of the strategy whose table contains the row, as written. A strategy named only in the row's Cross intervention or Strategy map column is not added. |
| students_targeted_exact | The plan's own words for the target group of that row, even when they don't fit the demographic codes (e.g. "All students within the 'Enhanced Support to Address Disadvantage' target group", coded `other`); where the row names no group, its strategy's group. Where the row names a group, don't add the strategy's group to it, even if the provider probably meant it (e.g. a row for "economically disadvantaged students" in a female progression strategy is `low_income` only, not combined with `sex`). For a merged activity, the group from each strategy it belongs to, joined with "and". No place names or strategy wording that isn't in the row. The group comes from the row itself: its Activity/Description cell, a student group column, or the activity's name where the name states the group (e.g. "Programme of Support for Students who are First in Family (FiF) to HE"; David, 22 Nov). Never the Outcomes or Inputs columns, a neighbouring row or the delivering staff. Use the strategy's targets or objectives only when the row mentions no targeting of students at all (David, 22 Nov). When the strategy's group is used, use all of it in the plan's words; where the strategy defines its group only through targets, use the targets' groups. Where the plan says the activity is for all students, "all students". |
| target_demographics | Only the codes the plan states, for the group in students_targeted_exact plus any group the row's own Outcomes column names (David, 6 Nov; the same as for lifecycle stages). A named region (e.g. "North East") is `region` only, never `area_based`, `low_income` or `fsm` on its own, and only when the row itself names the place. Don't add codes by inference: IMD or TUNDRA quintiles are `area_based` only, not also `fsm` or `low_income`; "young" or "young people" adds `age`; a level or year of study doesn't. "Eligible students" with no criteria stated is `all_students`. Use `all_students` together with specific codes only where the provision is open to all students but targets particular groups; where it is only for some students, use the specific codes alone (David, 22 Nov). Don't add `age` unless the row states an age group. Higher technical qualifications, foundation pathways and similar routes are `entry_route`. Mental health is `mental_health`, not `disability` (keep `disability` only where disabled students are also named). Full-time or part-time study is `mode_of_study`. ABCS is `abcs`. Pre-entry work is identified by the `pre_entry_attainment` lifecycle stage: don't code `age` or `other` for school pupils unless an age group or other group is named; a row naming only a school stage is `all_students`. Bursaries and financial support are `low_income` where eligibility is means-tested or based on household income, even if "low income" isn't written (David, 26 Nov). "Working class" is `low_income`; "socio-economic(ally) disadvantaged", "most deprived" or "disadvantaged" with no measure named is `other`, not `low_income` (David, 22 Nov) (with the measure named, use it: IMD is `area_based`, free school meals `fsm`). "Minoritised" or "underrepresented" students without the groups named, and vague phrases such as "targeted student groups at risk", are `other`. Apprentices are `other`; T Levels, BTEC and Access to HE are `entry_route`; service children are `military`. Allowed codes: age, disability, mental_health, mode_of_study, abcs, ethnicity, sex, lgbtq, region, area_based, fsm, low_income, first_in_family, care_experienced, estranged, carer, parents, military, gtrsb, refugee_asylum, child_in_need, ex_prisoner, religion, commuter, entry_route, all_students, other. |
| demographics_combined | True when any one of the groups has two or more characteristics at once (e.g. "young white males from IMD Q1 and Q2"), even if separate groups are also named (David, 6 Nov); False only when every group has a single characteristic. A region alone doesn't make a group combined ("ABMO students in the North East" is False). |
| lifecycle_stages | The stages the row states in any of its columns, including Outcomes (David, 6 Nov), plus the stage of its strategy's target(s). Pre-16 attainment work with school pupils is `pre_entry_attainment`. Don't add stages from elsewhere: a continuation row in an attainment strategy is `continuation` and `attainment`, but an attainment strategy's rows don't also get `continuation` unless the row says so. Allowed: pre_entry_attainment, access, transition, continuation, completion, attainment, progression, whole_lifecycle. A summer school for new students is `transition`, not also `access`, unless the plan says so. |
| linked_target_ids | Start from the row's own outcomes (Outcomes or Outcome indicators column). Match each outcome to the objectives in the strategy's introduction and the plan's overall objectives table, then take the targets those objectives link to. A target of the strategy that none of the row's outcomes relates to is left out (e.g. a wellbeing row whose outcomes are continuation, completion and attainment doesn't get the strategy's progression targets; David, 22 Nov). Where the plan maps activities to objectives directly (e.g. an intervention matrix), use that mapping. Where the row gives its own target reference or names one target, use it. Targets listed as "related" or "secondary" objectives or targets count (David, 6 Nov). A target named only in a Cross intervention or Strategy map column doesn't. Only references in the provider's targets list: drop any that aren't, and leave the list empty if the strategy's target isn't in it. Where the plan numbers targets differently from the targets list, match by the aim, not the number; where an objective's number and description disagree, the description wins. A merged record takes the targets of every strategy it lists. |
| linked_targets_text | The aim of each linked target, taken from the targets dataset. Python sets this from linked_target_ids, so judge it only if it doesn't match the ids. |
| risks_to_equality_of_opportunity | The EORR risks the plan gives for that row (or, if the row gives none, for the strategy), in the format `EORR Risk N – name`. Record a risk only when the plan names it as an EORR risk, by number ("EORR Risk 6") or in the EORR's own words ("insufficient academic support", "cost pressures"). If the plan describes risks only in its own words or as statistics (e.g. "an 18.7 percentage point continuation gap"), the value is empty: never map them to EORR on the provider's behalf. If the plan numbers its own risks ("Group risk 1", "York risk 2"), never read that number as an EORR number: use the plan's own link to EORR (a mapping table, or own risks defined in EORR wording), and leave it empty if there is none. If the plan's EORR name and number disagree, the name wins. Where the plan says its risks are mapped to the EORR somewhere (a mapping table or a statement such as "these risks have been mapped against the OfS EORR"), keep the risks taken from that mapping (David, 22 Nov). Where a plan links risks to student groups and each strategy is for one group (e.g. Petroc), the group's risks are the strategy's risks; a group with no EORR risk named is empty (David, 22 Nov). Wording close to an EORR risk but not its own words (e.g. "application rates" for Risk 4) doesn't count. A merged record takes the risks of every strategy it lists. |
| page | The PDF page (the cover is page 1) where the row starts. |

Where the plan's activity table has its own student group or objective column (e.g. Bath's "Student Group / Objective": "Socio-economic (OBJ1.1 and 1.2)"), that column is the row's group and objectives: use it for students_targeted_exact, target_demographics and linked_target_ids, and don't add groups from the strategy's other objectives (David, 22 Nov).

EORR risks: 1 Knowledge and skills; 2 Information and guidance; 3 Perception of higher education; 4 Application success rates; 5 Limited choice of course type and delivery mode; 6 Insufficient academic support; 7 Insufficient personal support; 8 Mental health; 9 Ongoing impacts of coronavirus; 10 Cost pressures; 11 Capacity issues; 12 Progression from higher education.

## Character encoding

Treat `020` in place of ’ and `013` in place of – as an encoding fault, not an extraction error. Correct it in names; ignore it when judging descriptions.

## Verdicts

Use the same statuses and error types as the QA page:

| Status | When |
| --- | --- |
| Correct | The value is right. |
| Partly correct | Some of the value is right, e.g. one demographic code too many, or a few words changed. |
| Incorrect | The value is wrong. |
| Missing | The value is empty but the plan states it. |
| Unsure | The reviewer can't tell from the pages given. A person decides. |

Error types: `missing value`, `wrong value`, `extra value (inferred, not in the plan)`, `not copied exactly`, `taken from the wrong place`, `formatting only`.

Use `formatting only` (with status Partly correct) where the content is right but isn't in the standard format, for example risks written as "Risk 1: Knowledge and skills" instead of "EORR Risk 1 – Knowledge and skills". The correction is still made, so the data is stored consistently, but it isn't counted as an extraction error.

For every field that isn't Correct, give the corrected value in the same format as the extracted value (JSON lists stay JSON lists, e.g. `["area_based"]`), plus a quote of up to 30 words copied exactly from the plan, and its page. The quote is checked by a script; a correction whose quote can't be found on that page is treated as Unsure.

## Output format (one JSON object per record)

```json
{
  "record_id": "qa2-944e35fb59ca1b4e53f77db7",
  "is_intervention": "Yes",
  "duplicate_of": "",
  "fields": [
    {
      "field": "risks_to_equality_of_opportunity",
      "status": "Incorrect",
      "error_type": "wrong value",
      "corrected_value": "[\"EORR Risk 3 – Perception of higher education\"]",
      "evidence_quote": "EORR Risk 3",
      "evidence_page": 7
    }
  ]
}
```

Every one of the 11 fields gets an entry, including those that are Correct (with an empty corrected value and no quote).
