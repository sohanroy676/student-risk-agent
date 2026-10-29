export const MAX_STUDENT_ID = 2 ** 31 - 1;
export const MENTOR_ID_LIMIT = 128;

// Same rules as MentorId in app/api/admin.py: trimmed, 1..128 characters, no control characters.
const CONTROL = /[\x00-\x1f\x7f]/;

export function validStudentId(value: string): boolean {
  const id = Number(value);
  return (
    value.trim() !== "" &&
    Number.isInteger(id) &&
    id >= 1 &&
    id <= MAX_STUDENT_ID
  );
}

export function validMentorId(value: string): boolean {
  const trimmed = value.trim();
  return (
    trimmed.length >= 1 &&
    trimmed.length <= MENTOR_ID_LIMIT &&
    !CONTROL.test(trimmed)
  );
}

export function assignmentSummary(result: {
  changed: boolean;
  cases_moved: number;
}): string {
  if (!result.changed && result.cases_moved === 0) return "No change.";
  const moved =
    result.cases_moved === 0
      ? "no open case moved"
      : result.cases_moved === 1
        ? "1 open case moved"
        : `${result.cases_moved} open cases moved`;
  return result.changed ? `Assigned; ${moved}.` : `Mentor unchanged; ${moved}.`;
}

// The only detail keys the nightly screen shows (the API sends these and nothing else).
const RUN_LABELS: [string, string][] = [
  ["as_of", "Data as of"],
  ["data_quality", "Data quality"],
  ["skipped", "Skipped (outside a term)"],
  ["model_week", "Model week"],
  ["students_evaluated", "Students evaluated"],
  ["cases_opened", "Cases opened"],
  ["deferred", "Cases deferred (mentor limit)"],
  ["unassigned", "Students without a mentor"],
  ["reasons_written", "Reasons written"],
  ["drafted", "Drafts written"],
  ["moved_to_review", "Moved to review"],
  ["newly_overdue", "Newly overdue"],
  ["cause", "Cause"],
];

/** Labelled values for the known keys, in a fixed order; unknown keys are never shown. */
export function runRows(detail: Record<string, unknown>): [string, string][] {
  const rows: [string, string][] = [];
  for (const [key, label] of RUN_LABELS) {
    const value = detail[key];
    if (value === undefined || value === null || typeof value === "object")
      continue;
    rows.push([label, String(value)]);
  }
  return rows;
}
