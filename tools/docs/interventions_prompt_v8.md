## Interventions extraction prompt v8 (6 November 2026)

1. Task

You are extracting the interventions described in an English higher education provider's Access and Participation Plan (APP). The full plan is provided, followed by the provider's targets.

Find every intervention in the plan's intervention strategy activity tables and record it exactly as the plan describes it. Missing an intervention is as serious an error as recording one the plan does not describe. Do not add, summarise, explain or improve anything: where a field asks for the plan's words, copy them; where it asks for codes, use only what the plan states.

The provider's current targets (reference number: aim):
{PROVIDER_TARGETS}

2. Map the plan first

Before extracting anything, build strategies_found:
- List every intervention strategy, usually numbered 1, 2, 3 and so on. Check the numbering for gaps.
- For each strategy, record:
  - its number and title
  - the student groups, lifecycle stages and targets it states (usually under "Objectives and targets"), with the target reference numbers from the list above
  - the risks to equality of opportunity it states, copied from its own risk line, with the page
  - the name of every row in its activity table, in order, with its activity code if it has one (e.g. "ISM6")
  - Count only rows of the activity table. Bullet points inside a row are part of that row. Rows of the evaluation table are not activities.
- Note the column headings of each activity table (for example Activity | Inputs | Outcomes | Cross intervention). You will need them to keep each column's text separate.
- Read the narrative before and after every table, its headings, objectives, footnotes and continuation pages. Target links and risks often appear there rather than in the activity row.
- Several strategies often share a page. Keep each strategy's objectives, targets and risks with that strategy only: never carry a risk, group or target from a neighbouring strategy on the same page.
- List any other sections that describe things the provider does or funds (for example financial support or mental health services) in other_sections_found, with their pages.


After identifying the activity rows, choose each record's source title before filling strategies_found.activities. Use the same spelling, full code, subtitle and non-status parentheses in the map and intervention_name; remove only the activity-status label from both. Do not use a shortened label in one and a longer label in the other. Do not append a description or invent a name for an untitled row.

Where the same activity is genuinely repeated and merged under section 3, choose its title from the first activity-table occurrence as the record name, and use that same name in every strategy map that points to this record. Keep the original description rules and combine the context of all listed strategies. Distinct activities must retain distinct records even where their codes or titles overlap.

3. What to extract

- One record for each row of each activity table.
- Rows that only describe running or evaluating the work (for example "Administration", "Evaluation", "Monitoring and evaluation", "Programme management") are not records.
- Where a strategy shows its activities in a diagram or graphic with short labels, and the plan then describes each activity in its own paragraph under its own heading, each labelled activity is a row: take its name from the paragraph heading and its description from that paragraph.
- A row belongs only to the strategy whose activity table it is in. A strategy named in a row's "Cross intervention", "Strategy map" or "Links to" column does not add that strategy, its targets or its risks to the row.
- Only rows of strategy activity tables are records. A bursary, scholarship, hardship fund, service or programme that is a row in a strategy table is a record; one described only elsewhere in the plan is not. List those in other_sections_found instead.
- The same activity in two tables is one record. Where a row says "as explained in intervention 4", or repeats an activity from another strategy, create one record and list both strategies. The record then combines the student groups, lifecycle stages, targets and risks of every strategy it lists (for example, an activity in a TUNDRA progression strategy and a mental health progression strategy takes both groups, both strategies' targets and both risk lines).
- Same name, different activity: keep them separate. Where two rows share a name but have different student groups, numbers or costs, they are separate records. Similar names are not the same activity: "Curriculum Design" in one strategy and "Curriculum Intent" in another are two records, and so are "YSJ Scholarships" and "YSJ Scholarships Plus".
- Activity codes can be reused for different activities in different strategies. For example, one plan uses "ISM6" for a programme of mental health events in one strategy, autism awareness events in another and dyslexia awareness events in a third: these are three records. Decide by the description, never by the code: merge two rows only when they describe the same activity, or when one row says it repeats the other (e.g. "[Repeated in 4.2 and 4.4]" or "See ISM9 in 4.3").

Before returning, check every activity row in strategies_found has exactly one record, that every code used for different activities has a record for each, and that no two records describe the same row of the same table.

Preserve complete activity identifiers exactly as printed. IS1.3 and IS1.4 are different identifiers; IS1 (i) and IS1 (ii) are different identifiers. Do not shorten either pair to IS1, drop a suffix, renumber activities, or invent an identifier. A row containing only a reference such as "See 4.5" or "IST1; IST2; IST3" updates the referenced records' strategy links; it does not create an additional combined record. If the reference cannot be resolved, flag the relevant record for review instead of inventing a new activity.


4. Fields

Use null or an empty list where the plan does not give the information. Never guess.

- intervention_name: copy the title in the Activity column word for word, including the full identifier, numbering, subtitle, acronym and all parentheses that are part of the title. Remove only a clearly identifiable activity-status label and put it in activity_status. Preserve small words such as "of", "the" and "and" and explanatory wording such as "(as noted in intervention strategy 3)". Do not summarise a long title, substitute a familiar name, or add words from Inputs or Outcomes. Where an Activity cell has no separate heading, use its first complete sentence as the name, or the whole cell if it is only one sentence; do not invent a short heading.
- activity_status: copy the activity-status label exactly, without its enclosing brackets, or return null if none is stated. Status labels can appear in brackets or on a separate line and include "New", "New activity", "Existing activity", "Ongoing activity", "Enhanced activity", "Enhanced Existing Activity", "New & Existing activity", "Existing and new collaborative activity" and "Extension to existing resource". Only separate wording that is clearly a status label: "Enhanced Support" in a programme name and "(AR)" in an acronym remain part of intervention_name. Never leave a separated status in strategies_found.activities or intervention_name.
- intervention_description: the text of the row's Activity (or Description) column, copied word for word, after the title. Keep every word, including bullet points and phrases such as "This will include:". Do not shorten, paraphrase, merge sentences, add a purpose ("to increase...") or add who it is for. Never use text from the Inputs, Outcomes, Cross intervention or Evaluation columns, even where the Activity cell is short. Resources such as "Staff time and access to on-campus resources" or "0.5 FTE coordinator" are inputs, not descriptions: in a table where text runs across columns, keep only the text that sits under the Activity heading. Where the cell continues on the next page, join the two parts. Where the Activity cell is a single sentence used as intervention_name and has no further Activity/Description text, return null for the description; do not fill it from another column. Line wrapping can be joined with spaces while preserving the source words, order, punctuation and bullet structure. Do not treat text interleaved from a neighbouring column as part of the activity. If the supplied text does not establish a cell boundary, retain only wording that can be attributed to the activity and set flag_for_review=true with a specific reason.
- intervention_strategy: a list of the number and title of each strategy whose activity table lists it. A repeated activity merged into one record may list multiple strategies, as in v1. A strategy named only in the row's Cross intervention, Strategy map or "Links to" column is not added.
- in_strategy_table: always true (kept so the output format doesn't change).
- students_targeted_exact: who the activity is for, copied word for word from the activity row. Where the row names a group, use only that group, even if the strategy is about a wider group. Don't add place names, the strategy's title or other wording that isn't in the row. For a merged activity, give the group for each strategy it belongs to, joined with "and" (e.g. "Students with diagnosed mental health conditions and students with social and communication disabilities"). Where the activity is delivered to staff for students' benefit, copy the row's wording (e.g. "Academic staff and personal tutors supporting students with dyslexia"). Where the row names a specific group that doesn't fit the codes below (e.g. "All students within the 'Enhanced Support to Address Disadvantage' target group"), still copy it exactly, and code it as other unless the plan defines the group elsewhere. If the row does not say, copy the group from its own strategy's objectives (e.g. "Graduates from TUNDRA Q1 and Q2"), not a general phrase. Never use a group from a different strategy.
  - Read the group from the Activity (or Description) cell or the table's own student group column. The activity's name is not a group, and neither are the Outcomes or Inputs columns, a neighbouring row, or the staff who deliver the activity (e.g. "staff on our audition panels").
  - When you take the strategy's group, take all of it, in the plan's words: a strategy for "minority ethnic students, students from areas of multiple deprivation and those with multiple risk characteristics" gives that whole phrase, not "minority ethnic students". Where the strategy defines its group only through its targets (e.g. "groups targeted by PTS_1 to PTS_4"), use the groups those targets name.
  - Where the plan says the activity or strategy is for all students and names no group, write "all students".
- target_demographics: codes for the students named in students_targeted_exact (for staff-facing activities, the students they support), plus any student group the row's own Outcomes column names (e.g. outcomes of "Increased number of applications from Free school meal (FSM) white males" add fsm), as for lifecycle_stages. Nothing else: not groups from a neighbouring row or another strategy. Map them like this:
  - a named geographical region (e.g. "North East", "North West", "Yorkshire and the Humber") -> region only, and only where the row itself names the place (not the strategy's title or objectives). A region is not evidence of deprivation, low income or free school meal eligibility. Do not add area_based, low_income or fsm from a regional label, regional averages or assumptions about the region. Do not infer region from the provider's address; the targeted group must explicitly name it.
  - IMD, TUNDRA, POLAR, "deprived areas", "low participation neighbourhoods" -> area_based only (not fsm, not low_income)
  - free school meals -> fsm; household income, means-tested, bursary eligibility, "economically disadvantaged", "low socioeconomic" -> low_income
  - "young", "under 21", "mature", "21 and over" -> age. A school year group alone ("Year 9 pupils") does not add age.
  - Black, Asian, mixed, global majority, BAME, ABMO, white -> ethnicity
  - male, female, women, men -> sex
  - disability, disabled, mental health condition, neurodivergent, dyslexia -> disability
  - "all students" with no group -> all_students. "Eligible students" where the row doesn't say what makes them eligible -> all_students.
  - "working class", "most deprived", "disadvantaged backgrounds" with no measure named -> low_income. Where the plan names the measure, use it (IMD -> area_based; free school meals -> fsm).
  - "minoritised" or "underrepresented" students where the row doesn't name the groups, and vague phrases such as "targeted student groups at risk" -> other.
  - "young people" -> age. A level or year of study ("Level 5, 6 and 7 students", "final-year students") is not age and adds no code.
  - apprentices and other groups the codes don't cover -> other; a qualification route such as T Levels, BTEC or Access to HE -> entry_route; service children -> military.
  Examples: "students from the North East" -> ["region"]; "low-income students from the North East" -> ["region", "low_income"]; "FSM-eligible pupils in the North East" -> ["region", "fsm"]; "students from IMD Q1 in the North East" -> ["region", "area_based"]. Each additional characteristic needs its own explicit evidence.
- demographics_combined: true where any one of the groups has two or more characteristics together (e.g. "young white males from IMD Q1 and Q2" = age, ethnicity, sex, area_based, true), even if the row or strategy also names other, separate groups ("males from IMD Q1-2, and students with mental health conditions" is true). False only where every group has a single characteristic. A region alone doesn't make a group combined: "ABMO students in the North East" is false.
- lifecycle_stages: the stages the activity row states in any of its columns, including Outcomes (e.g. "aligned to student retention/continuation" adds continuation; "graduate development" or graduate internships add progression), plus the stage of its own strategy's targets. Do not add a stage the plan does not name:
  - access: getting into higher education. Add transition only where the plan describes the move into the first year (induction, summer schools for new entrants, the first weeks).
  - attainment: degree outcomes (good honours, awarding gaps). Do not add it for continuation or completion work unless the plan names attainment or the strategy's target is an attainment target.
  - whole_lifecycle: only where the plan says the activity covers the whole student lifecycle. Where it names stages, list those stages.
  - pre_entry_attainment: only work with school pupils to raise their attainment, including pre-16 attainment (e.g. "increase pre-16 attainment of underrepresented students").
- linked_target_ids: the target reference numbers that the activity's own strategy lists, read from its objectives and targets text, table introduction, footnotes and continuation pages. Include every target the strategy lists, on every row of its table, unless the row explicitly narrows them: a row that gives its own target reference (e.g. "(FIT target reference number - PTS_2)") or names one target links to that target only. Do not link or drop a target because of the row's topic. Where the strategy names a target in words (e.g. "to increase year on year the number of school staff undertaking a digital upskilling programme"), match it to the target in the list above whose aim says the same thing. Use only reference numbers from the list above; where the strategy lists no targets, or one you cannot match, return [] and flag it.
  - Targets the strategy lists as "related" or "secondary" objectives or targets (e.g. "Related objectives and targets: PTS_1, PTS_2", "Secondary objectives: PTS_2 & PTA_4") count, as well as its main ones.
  - A target or strategy named only in a row's Cross intervention, Strategy map or "Links to" column does not add a target.
  - Where the plan numbers its objectives or targets differently from the list above (e.g. the plan calls the Black students target PTA_3 but the list has it as PTA_4), match by what the target is about, using the aims in the list, not by the number.
  - Where the plan's objective number and its description disagree (e.g. "Objective 6: ...successfully continue and complete their courses" when Objective 6 is the progression objective), the description wins.
  - Drop any reference that is not in the list above (e.g. a "secondary objective PTS_4" when the provider has no PTS_4), and flag it.
- target_link_scope: "strategy" when the strategy's target list applies to the activity without restriction; "activity" when the row explicitly narrows or excludes strategy targets, or an outside-table activity has its own explicit links; "unresolved" when the association is unclear. For an activity merged across several tables, include the explicit links from its listed strategies. 
- risks_to_equality_of_opportunity: the risks stated for this row, or, if the row states none, on its own strategy's risk line. Give each as "EORR Risk N – name", using the list below. Risk labels often sit at the end of a row, or at the top of the next page when a row runs over, and belong to that row.
  - Record a risk only when the plan names it as an EORR risk: by its EORR number ("EORR Risk 6", "Risk 6") or in the EORR's own words ("risks... in relation to insufficient academic support, cost pressures" gives Risks 6 and 10).
  - Where the plan describes its risks only in its own words or as statistics (e.g. "an 18.7 percentage point continuation gap", "students may feel they don't belong"), return []. Never map these to EORR on the provider's behalf.
  - Where the plan numbers its own risks ("Group risk 1", "York risk 2", "UEA Risk 5"), never read that number as an EORR number. Use the plan's own link to the EORR (a mapping table, or its own risks defined in EORR wording), and return [] if there is none.
  - Where the plan's EORR name and number disagree (e.g. "Insufficient academic support (Risk 5)"), the name wins: EORR Risk 6.
  - Return [] where neither the row nor its strategy states an EORR risk.
- risks_evidence: the words copied exactly from the plan that state the risks (e.g. "EORR Risk 6 / 7/ 8"), with the page.

A merged activity uses the groups, stages, targets and risks of each strategy whose table lists it; it does not become a separate record for each strategy. Check this carefully for risks: list the risks from every listed strategy's risk line, not just the first.
- page: the number of the PDF page where the activity's row starts (a script will check this against the PDF text), counting the PDF's own pages from 1 (the cover is page 1). Ignore the page numbers printed on the pages, which often differ by one or more. Where a row starts at the bottom of one page and continues on the next, use the first page.
- flag_for_review: true where you were unsure, for example about a target link, a risk mapping or a demographic code.
- flag_reason: one short sentence explaining the flag, or null.

Write apostrophes and dashes as ’ and – (never as codes such as 020 or 013).

EORR risks: 1 Knowledge and skills; 2 Information and guidance; 3 Perception of higher education; 4 Application success rates; 5 Limited choice of course type and delivery mode; 6 Insufficient academic support; 7 Insufficient personal support; 8 Mental health; 9 Ongoing impacts of coronavirus; 10 Cost pressures; 11 Capacity issues; 12 Progression from higher education.

Target demographics codes: age, disability, ethnicity, sex, lgbtq, region, area_based, fsm, low_income, first_in_family, care_experienced, estranged, carer, parents, military, gtrsb, refugee_asylum, child_in_need, ex_prisoner, religion, commuter, entry_route, all_students, other.

Lifecycle codes: pre_entry_attainment, access, transition, continuation, completion, attainment, progression, whole_lifecycle.


Before producing the final JSON:
- Reconcile every activity-table row with its record after the existing merge rules. Every entry in strategies_found.activities must point to a returned intervention_name. Do not return a complete strategy map with only a sample of its records.
- Keep activity_count as the number of activity-table rows in that strategy, not the number of bullets or evaluation-table rows. Repeated activities can map to one record across strategies; the plan-wide record count need not equal the sum of all activity_count values.
- Confirm every record's title and description against its own activity row, and use the supplied === PAGE N === marker for the PDF page where the row starts. A table continuation or repeated mention is not evidence that the row starts on that later page. Never substitute the printed footer number.
- If the supplied pages contain only page numbers, headers or footers, do not infer that the plan has no interventions and do not invent records to fill the JSON schema. Return only supported data. A program must detect this condition and obtain readable text or OCR before the extraction can be treated as complete.

Field examples (format illustrations only; do not copy these values unless they occur in this plan):
- Source: IS1.3 Scholars programme (Enhanced Existing Activity) -> intervention_name: "IS1.3 Scholars programme"; activity_status: "Enhanced Existing Activity"; map activity: "IS1.3 Scholars programme".
- Source: Aspiration raising (AR) -> intervention_name: "Aspiration raising (AR)"; activity_status: null. AR is part of the title.
- Source: Embedding inclusive pedagogies (as noted in intervention strategy 3) linking with Curriculum Redefined -> keep the complete wording, including the parenthesis, in both the name and map.

5. Output

Return only JSON in this shape, with no other text. The values below show the format only; never copy them.
{
  "strategies_found": [
    {"number": "1", "title": "<strategy title>", "student_groups": ["<group>"], "lifecycle_stages": ["<code>"],
     "target_ids": ["<PTx_n>"], "risks_to_equality_of_opportunity": ["EORR Risk <n> – <name>"],
     "activities": ["<row name>"], "activity_count": 0}
  ],
  "other_sections_found": ["<section name> (p<n>): <items>"],
  "interventions": [
    {"intervention_name": "<as written, without status label>", "activity_status": null,
     "intervention_description": "<word for word>",
     "intervention_strategy": ["<n> <title>"], "in_strategy_table": true,
     "students_targeted_exact": "<word for word>",
     "target_demographics": ["<code>"], "demographics_combined": false, "lifecycle_stages": ["<code>"],
     "linked_target_ids": ["<PTx_n>"], "target_link_scope": "strategy",
     "risks_to_equality_of_opportunity": ["EORR Risk <n> – <name>"],
     "risks_evidence": {"text": "<copied from the plan>", "page": 0},
     "page": 0, "flag_for_review": false, "flag_reason": null}
  ]
}

Record only what the provider says it is doing. Do not judge whether an intervention is effective or well designed.
