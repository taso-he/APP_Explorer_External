# Interventions extraction prompt v8: changes from Mikayla's v7

v8 is Mikayla's v7 (3 November) with the rules agreed in the review of the first 67 plans added. Nothing in v7 was taken out except the instruction to map risks described in the plan's own words onto EORR numbers, which conflicted with the rule agreed on 5 November. The same rules are in `interventions_qa_rules.md`, which the Claude reviewer reads, so the extraction and the check follow one set of rules.

## Section 3: what to extract

1. **Administration and evaluation rows are not records** (proposed 5 Nov). They were 14 of the first 20 "possible missing records".
2. **Strategies shown as diagrams.** Where the activities are short labels in a graphic and each is then described in its own paragraph (University of Suffolk), the paragraph gives the name and description.
3. **Cross intervention and Strategy map columns don't add a strategy** to a row, or its targets and risks (TEC Partnership, University of Sheffield).
4. **Similar names aren't the same activity** ("Curriculum Design" and "Curriculum Intent" at Heart of Yorkshire; "YSJ Scholarships" and "YSJ Scholarships Plus").
5. **No table row extracted twice** (179 records, 12%, in the first run). Added to the final check.

## Section 4: fields

6. **students_targeted_exact** (5 Nov): the activity's name, the Outcomes and Inputs columns, a neighbouring row and the delivering staff are not the group; take the strategy's whole group, in its words; use the targets' groups where that's how the strategy defines them; "all students" where the plan says so.
7. **target_demographics** (6 Nov): groups named in the row's Outcomes column count, as they do for stages (Sheffield Hallam 4.2's "FSM white males"), though students_targeted_exact still comes from the Activity cell or the strategy; "eligible students" with no criteria is all_students; "working class" or "most deprived" with no measure is low_income; unnamed "minoritised" groups and vague phrases are other; "young people" adds age, a level of study doesn't; apprentices other; T Levels, BTEC and Access to HE entry_route; service children military.
8. **demographics_combined** (6 Nov): true if any one group combines characteristics, even alongside separate groups.
9. **lifecycle_stages** (6 Nov): stages named in any column of the row count, including Outcomes; pre-16 attainment work is pre_entry_attainment.
10. **linked_target_ids** (6 Nov): "related" and "secondary" targets count; Cross intervention columns don't; match by the aim where the plan numbers targets differently from the targets list (University of Bradford); an objective's description beats its number (City of Liverpool College); drop references that aren't in the list (York College's PTS_3 and PTS_4).
11. **risks_to_equality_of_opportunity** (5 Nov): EORR only, by number or EORR wording; never mapped from the plan's own words or statistics; a plan's own risk numbering is not EORR numbering; where an EORR name and number disagree, the name wins. This replaces v7's "map it to the matching EORR numbers".
12. **intervention_strategy**: a strategy named only in the Cross intervention or Strategy map column is not added.
