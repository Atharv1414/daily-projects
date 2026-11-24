# Requirements and traceability

## Pain points

| Id | Pain point | Evidence metric |
|---|---|---|
| PP1 | Written summaries wait in one administrator's queue and are typed by hand. | met_summary |
| PP2 | Make-safe jobs queue behind routine repairs because work is first come, first served. | met_make_safe |
| PP3 | Survey visits fail because nobody is home, then wait days to be rebooked. | no_access_visits |
| PP4 | Every case gets a survey visit and a post inspection, whatever its risk. | inspections |
| PP5 | Nobody can see a statutory clock until it has been missed. | met_investigate |
| PP6 | Triage and inspection records are missing, so compliance cannot be evidenced. | conformance |

## Traceability matrix

| Story | Priority | Points | Solves | Want | KPI | Target | Phase | Simulated | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| US01 | Must | 5 | PP5 | every open case to show its statutory clocks and time remaining | met_investigate | 0.98 | 1 | 0.993 | met |
| US02 | Must | 8 | PP2, PP5 | jobs ordered by statutory deadline | met_make_safe | 0.98 | 1 | 1.000 | met |
| US03 | Must | 5 | PP1 | one summary queue, a standard template and a second trained administrator | met_summary | 0.98 | 1 | 1.000 | met |
| US04 | Must | 3 | PP5 | emergencies dispatched to a crew as soon as they are triaged | met_emergency | 0.99 | 1 | 1.000 | met |
| US05 | Must | 3 | PP6 | a case to be impossible to close without triage, summary and completion evidence | conformance | 1 | 1 | – | not modelled |
| US06 | Must | 5 | PP6 | an unchangeable log of every milestone and who recorded it | conformance | 1 | 1 | – | not modelled |
| US07 | Could | 8 | PP4 | to assess low-risk cases from photos and readings | surveys | 4600 | 2 | 4,233.5 | met |
| US08 | Could | 5 | PP3 | to choose and confirm a visit time by text or phone | no_access_visits | 600 | 2 | 410.3 | met |
| US09 | Could | 5 | PP4 | post inspections selected by risk | inspections | 2500 | 2 | 1,803.1 | met |
| US10 | Should | 3 | PP3 | a failed visit to release a new slot within 2 working days | met_investigate | 0.98 | 1 | 0.993 | met |
| US11 | Could | 5 | PP2 | common damp parts forecast and stocked | mean_days | 13 | 2 | 13.1 | NOT MET |
| US12 | Could | 3 | PP5 | to see where my case is | mean_days | 13 | 2 | 13.1 | NOT MET |
| US13 | Won't | 13 | PP4 | humidity sensors in every home | cases | 0 | 2 | – | not modelled |

## Stories

**US01 (Must).** As a compliance manager, I want every open case to show its statutory clocks and time remaining, so that I can act before a limit is missed.

**US02 (Must).** As a works planner, I want jobs ordered by statutory deadline, so that make-safe work is never stuck behind routine repairs.

**US03 (Must).** As a repairs administrator, I want one summary queue, a standard template and a second trained administrator, so that every tenant hears within 3 working days.

**US04 (Must).** As a duty officer, I want emergencies dispatched to a crew as soon as they are triaged, so that the home is made safe within 24 hours.

**US05 (Must).** As a auditor, I want a case to be impossible to close without triage, summary and completion evidence, so that we can prove what happened.

**US06 (Must).** As a head of compliance, I want an unchangeable log of every milestone and who recorded it, so that evidence stands up to the Ombudsman.

**US07 (Could).** As a surveyor, I want to assess low-risk cases from photos and readings, so that visits go to homes that need them.

**US08 (Could).** As a tenant, I want to choose and confirm a visit time by text or phone, so that I do not miss the surveyor.

**US09 (Could).** As a quality manager, I want post inspections selected by risk, so that surveyor time is spent on surveys.

**US10 (Should).** As a scheduler, I want a failed visit to release a new slot within 2 working days, so that the clock does not run while nobody acts.

**US11 (Could).** As a stores manager, I want common damp parts forecast and stocked, so that repairs start sooner.

**US12 (Could).** As a tenant, I want to see where my case is, so that I do not have to call.

**US13 (Won't).** As a asset manager, I want humidity sensors in every home, so that damp is found before it is reported.

