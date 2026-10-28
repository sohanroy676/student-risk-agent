// Shapes of the API responses this app reads (see app/api/cases.py). Only the band is ever
// shown for a case: the API never sends a probability or score, and neither should the UI.

export type Role = "admin" | "staff" | "mentor" | "faculty";

export type CaseState =
  | "new"
  | "drafted"
  | "monitoring"
  | "in_review"
  | "escalated"
  | "resolved"
  | "dismissed";

export type CaseAction =
  | "approve"
  | "dismiss"
  | "continue"
  | "resolve"
  | "escalate";

export interface CaseSummary {
  id: number;
  student_id: number;
  mentor_id: string;
  state: CaseState;
  band: "amber" | "red";
  reason: "red" | "rapid_rise";
  cycle: number;
  opened_on: string;
  entered_on: string;
  due_on: string | null;
  overdue: boolean;
  approved_by: string | null;
  approved_on: string | null;
}

export interface CasePage {
  items: CaseSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface TimelineEvent {
  on_date: string;
  kind: string;
  from_state: string | null;
  to_state: string | null;
  actor_kind: string;
  actor_id: string | null;
  detail: Record<string, string | boolean>;
}

export interface CaseReason {
  rank: number;
  fact_id: string;
  feature: string;
  text: string;
}

export interface Draft {
  version: number;
  source: "template" | "agent" | "mentor";
  author: string;
  created_on: string;
  message: string;
}

export interface CaseDetail extends CaseSummary {
  timeline: TimelineEvent[];
  reasons: CaseReason[];
  draft: Draft | null;
}
