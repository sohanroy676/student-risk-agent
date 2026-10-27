# Project Brief

## What it is
An early-warning module for college ERP systems. Each night it scores students for risk from ERP and LMS data, explains each score in three plain reasons, and has an AI agent draft an intervention for the faculty mentor to approve. It is built to work for any college and will be tested first at our own college.

## Success criteria for v1
A complete prototype with all main features working end to end: data ingest, risk scoring with explanations and a fairness report, case creation, agent-drafted plans, mentor approval, message sending, 7-day follow-up and escalation, a web dashboard for each role, and an audit log. Targets from the blueprint (e.g. week-1 AUC at least 0.72 and week-8 AUC at least 0.86 on OULAD, 0 banned-term leaks, all crisis cases routed to people) are the measure.

## Out of scope
Nothing is declared out of scope for now. The blueprint does say the system makes no automated decisions (detention, fines, grades) and does not show scores to students or parents. Those are design rules, not scope cuts.