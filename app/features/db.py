"""Load `CoreTables` from Postgres for a given `as_of`.

The queries already drop rows dated after `as_of` and blank out a `paid_on` that falls
after it, so the database never hands later facts to the builder. The builder filters
again by itself, so either layer alone keeps the snapshot point-in-time.
"""

from datetime import date

import pandas as pd
from sqlalchemy import Connection, text

from app.features.tables import CoreTables

QUERIES = {
    "enrollments": "SELECT student_id, course_id FROM core.enrollments",
    "attendance": """
        SELECT student_id, course_id, class_date, present
        FROM core.attendance WHERE class_date <= :as_of""",
    "assessments": "SELECT id, course_id, due_date, max_marks FROM core.assessments",
    "marks": """
        SELECT assessment_id, student_id, marks_obtained, submitted_on
        FROM core.marks WHERE submitted_on <= :as_of""",
    "fees": """
        SELECT student_id, due_date, amount,
               CASE WHEN paid_on <= :as_of THEN paid_on END AS paid_on
        FROM core.fees WHERE due_date <= :as_of""",
    "lms_events": """
        SELECT student_id, course_id, occurred_at, event_type
        FROM core.lms_events WHERE occurred_at < CAST(:as_of AS date) + 1""",
}


def load_core_tables(conn: Connection, as_of: date) -> CoreTables:
    frames = {
        name: pd.read_sql(text(sql), conn, params={"as_of": as_of}) for name, sql in QUERIES.items()
    }
    return CoreTables.from_frames(**frames)
