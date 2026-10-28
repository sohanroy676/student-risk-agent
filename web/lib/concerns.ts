import type { ConcernCategory } from "./types";

export const NOTE_LIMIT = 500; // the API's limit (app/api/concerns.py)

export const CATEGORIES: { value: ConcernCategory; label: string }[] = [
  { value: "attendance", label: "Attendance" },
  { value: "performance", label: "Performance in class" },
  { value: "wellbeing", label: "Wellbeing" },
  { value: "behaviour", label: "Behaviour" },
  { value: "other", label: "Something else" },
];

export function categoryLabel(category: ConcernCategory): string {
  return CATEGORIES.find((c) => c.value === category)?.label ?? category;
}
