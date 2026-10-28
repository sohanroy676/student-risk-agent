import type { ModelRelease } from "./types";

/** The fairness limit the gate uses (app/ml/gate.py); the gate, not this number, decides. */
export const RECALL_GAP_LIMIT = 0.1;

export function number3(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : value.toFixed(3);
}

/** Plain-words description of a block or failure code from the gate. */
export function explainCode(code: string): string {
  if (code === "auc_lower")
    return "Week-4 AUC is lower than the model now in production.";
  if (code === "ece_high") return "Calibration error is above the limit.";
  if (code.startsWith("gap_high:")) {
    return `Recall differs between ${code.slice("gap_high:".length)} groups by more than the limit.`;
  }
  if (code.startsWith("unassessed:")) {
    return `${code.slice("unassessed:".length)} could not be assessed (too few students in a group).`;
  }
  if (code.startsWith("missing:"))
    return `${code.slice("missing:".length)} is missing.`;
  return code;
}

export function gateSummary(release: ModelRelease): string {
  const gate = release.gate_now;
  if (gate === null) return "No verdict";
  if (gate.hard_failures.length > 0) return "Cannot be promoted";
  if (gate.passed) return "Passes the gate";
  return `Blocked (${gate.blocks.length})`;
}
