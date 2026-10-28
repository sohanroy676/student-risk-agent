// Which buttons to offer on a case. This mirrors the API's rules (app/cases/states.py) only so
// the screen does not offer moves that are certain to fail; the API still decides every move.

import type { CaseAction, CaseState, Role } from "./types";

export const OPEN_STATES: CaseState[] = [
  "new",
  "drafted",
  "monitoring",
  "in_review",
  "escalated",
];

const RULES: Record<CaseAction, { from: CaseState[]; roles: Role[] }> = {
  approve: { from: ["drafted"], roles: ["mentor"] },
  continue: { from: ["in_review"], roles: ["mentor"] },
  resolve: { from: ["in_review", "escalated"], roles: ["mentor", "staff"] },
  escalate: {
    from: ["new", "drafted", "monitoring", "in_review"],
    roles: ["mentor", "staff"],
  },
  dismiss: {
    from: ["new", "drafted", "in_review"],
    roles: ["mentor", "staff"],
  },
};

export const ACTION_ORDER: CaseAction[] = [
  "approve",
  "continue",
  "resolve",
  "escalate",
  "dismiss",
];

export const ACTION_LABEL: Record<CaseAction, string> = {
  approve: "Approve draft",
  continue: "Continue monitoring",
  resolve: "Mark resolved",
  escalate: "Escalate to a person",
  dismiss: "Dismiss",
};

export function actionsFor(state: CaseState, role: Role): CaseAction[] {
  return ACTION_ORDER.filter(
    (a) => RULES[a].from.includes(state) && RULES[a].roles.includes(role),
  );
}

/** Only the case's own mentor may reword the draft, and only before it is approved. */
export function canEditDraft(state: CaseState, role: Role): boolean {
  return role === "mentor" && state === "drafted";
}

export const STATE_LABEL: Record<CaseState, string> = {
  new: "New",
  drafted: "Draft ready",
  monitoring: "Monitoring",
  in_review: "Follow-up review",
  escalated: "Escalated",
  resolved: "Resolved",
  dismissed: "Dismissed",
};
