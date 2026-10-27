"""Deterministic synthetic college: one term of ERP- and Moodle-shaped data.

Every random draw comes from a single `numpy.random.Generator` seeded by `seed`,
so the same seed always yields identical tables. A fixed share of students is
"planted" as struggling (lower attendance, marks, submissions, LMS activity and
later fee payment); their ids are returned so tests and evals have ground truth.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

N_SECTIONS = 6
N_STUDENTS = 400
N_COURSES = 5
N_WEEKS = 15
CLASSES_PER_WEEK = 3
ASSESSMENT_WEEKS = (4, 8, 12, 14)
N_FEE_INSTALMENTS = 2
STRUGGLING_SHARE = 0.10
TERM_START = date(2026, 1, 5)  # a Monday
TERM_END = TERM_START + timedelta(weeks=N_WEEKS) - timedelta(days=1)
LMS_EVENT_TYPES = ("view", "forum_post", "quiz_attempt", "assignment_submit")
FEE_AMOUNT = 45000

N_ATTENDANCE = N_STUDENTS * N_COURSES * N_WEEKS * CLASSES_PER_WEEK
N_MARKS = N_STUDENTS * N_COURSES * len(ASSESSMENT_WEEKS)
N_FEES = N_STUDENTS * N_FEE_INSTALMENTS


@dataclass
class Table:
    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]


@dataclass
class SyntheticData:
    tables: dict[str, Table]
    struggling_ids: frozenset[int]


def _class_dates(course_id: int) -> list[date]:
    weekdays = [(course_id + k * 2) % 5 for k in range(CLASSES_PER_WEEK)]
    return [
        TERM_START + timedelta(weeks=w, days=d) for w in range(N_WEEKS) for d in sorted(weekdays)
    ]


def generate(seed: int = 42) -> SyntheticData:
    rng = np.random.default_rng(seed)
    student_ids = list(range(1, N_STUDENTS + 1))
    struggling = frozenset(
        int(i)
        for i in rng.choice(student_ids, size=round(N_STUDENTS * STRUGGLING_SHARE), replace=False)
    )
    is_struggling = np.array([s in struggling for s in student_ids])

    # Per-student latent behaviour: attendance probability and mark level (fraction of max).
    attend_p = np.where(is_struggling, rng.beta(5, 5, N_STUDENTS), rng.beta(17, 3, N_STUDENTS))
    mark_level = np.where(
        is_struggling, rng.normal(0.38, 0.08, N_STUDENTS), rng.normal(0.72, 0.08, N_STUDENTS)
    )
    submit_p = np.where(is_struggling, 0.55, 0.96)
    late_fee_p = np.where(is_struggling, 0.6, 0.05)
    lms_rate = np.where(is_struggling, 3.0, 12.0)  # events per week

    tables: dict[str, Table] = {}
    tables["terms"] = Table(
        ("id", "name", "start_date", "end_date"),
        [(1, "Term 1", TERM_START, TERM_END)],
    )
    tables["sections"] = Table(
        ("id", "name", "term_id"),
        [(s, f"Section {chr(64 + s)}", 1) for s in range(1, N_SECTIONS + 1)],
    )
    tables["courses"] = Table(
        ("id", "code", "title"),
        [(c, f"CS{100 + c}", f"Course {c}") for c in range(1, N_COURSES + 1)],
    )
    tables["students"] = Table(("id", "section_id"), [(i, i % N_SECTIONS + 1) for i in student_ids])
    tables["enrollments"] = Table(
        ("student_id", "course_id"),
        [(i, c) for i in student_ids for c in range(1, N_COURSES + 1)],
    )

    attendance: list[tuple[Any, ...]] = []
    for c in range(1, N_COURSES + 1):
        dates = _class_dates(c)
        # Struggling students' attendance decays over the term.
        decay = np.linspace(1.0, 0.7, len(dates))
        probs = np.where(
            is_struggling[:, None], attend_p[:, None] * decay[None, :], attend_p[:, None]
        )
        present = rng.random((N_STUDENTS, len(dates))) < probs
        for si, sid in enumerate(student_ids):
            attendance.extend((sid, c, d, bool(p)) for d, p in zip(dates, present[si], strict=True))
    tables["attendance"] = Table(("student_id", "course_id", "class_date", "present"), attendance)

    assessments: list[tuple[Any, ...]] = []
    marks: list[tuple[Any, ...]] = []
    aid = 0
    for c in range(1, N_COURSES + 1):
        for k, week in enumerate(ASSESSMENT_WEEKS, start=1):
            aid += 1
            due = TERM_START + timedelta(weeks=week - 1, days=4)
            assessments.append((aid, c, f"Assessment {k}", due, 100))
            submitted = rng.random(N_STUDENTS) < submit_p
            late = rng.random(N_STUDENTS) < np.where(is_struggling, 0.4, 0.05)
            late_days = rng.integers(1, 3, N_STUDENTS)
            scores = np.clip(rng.normal(mark_level, 0.10) * 100, 0, 100).round(1)
            for si, sid in enumerate(student_ids):
                if submitted[si]:
                    on = due + timedelta(days=int(late_days[si])) if late[si] else due
                    marks.append((aid, sid, float(scores[si]), on))
                else:
                    marks.append((aid, sid, None, None))
    tables["assessments"] = Table(
        ("id", "course_id", "title", "due_date", "max_marks"), assessments
    )
    tables["marks"] = Table(
        ("assessment_id", "student_id", "marks_obtained", "submitted_on"), marks
    )

    fees: list[tuple[Any, ...]] = []
    fid = 0
    for k in range(N_FEE_INSTALMENTS):
        due = TERM_START + timedelta(days=7 + 49 * k)
        is_late = rng.random(N_STUDENTS) < late_fee_p
        early = rng.integers(0, 6, N_STUDENTS)
        delay = rng.integers(10, 41, N_STUDENTS)
        for si, sid in enumerate(student_ids):
            fid += 1
            paid = (
                due + timedelta(days=int(delay[si]))
                if is_late[si]
                else due - timedelta(days=int(early[si]))
            )
            # Payments after term end are not yet known: record as unpaid.
            fees.append((fid, sid, due, FEE_AMOUNT, paid if paid <= TERM_END else None))
    tables["fees"] = Table(("id", "student_id", "due_date", "amount", "paid_on"), fees)

    lms: list[tuple[Any, ...]] = []
    for week in range(N_WEEKS):
        counts = rng.poisson(lms_rate)
        for si, sid in enumerate(student_ids):
            n = int(counts[si])
            days = rng.integers(0, 7, n)
            hours = rng.integers(8, 23, n)
            courses = rng.integers(1, N_COURSES + 1, n)
            kinds = rng.integers(0, len(LMS_EVENT_TYPES), n)
            for d, h, c, kd in zip(days, hours, courses, kinds, strict=True):
                at = datetime.combine(
                    TERM_START + timedelta(weeks=week, days=int(d)), datetime.min.time()
                )
                lms.append((sid, int(c), at + timedelta(hours=int(h)), LMS_EVENT_TYPES[int(kd)]))
    tables["lms_events"] = Table(("student_id", "course_id", "occurred_at", "event_type"), lms)

    genders = rng.choice(["F", "M", "O"], N_STUDENTS, p=[0.48, 0.5, 0.02])
    cats = rng.choice(["general", "obc", "sc", "st"], N_STUDENTS, p=[0.5, 0.3, 0.14, 0.06])
    tables["student_attributes"] = Table(
        ("student_id", "gender", "category"),
        [(sid, str(genders[i]), str(cats[i])) for i, sid in enumerate(student_ids)],
    )
    return SyntheticData(tables=tables, struggling_ids=struggling)


def write_csv(data: SyntheticData, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in data.tables.items():
        with (out_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(table.columns)
            w.writerows(["" if v is None else v for v in row] for row in table.rows)
    with (out_dir / "struggling_ids.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["student_id"])
        w.writerows([i] for i in sorted(data.struggling_ids))


def main() -> None:
    write_csv(generate(), Path("data/synthetic/out"))


if __name__ == "__main__":
    main()
