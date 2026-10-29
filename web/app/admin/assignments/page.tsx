"use client";

import { useState } from "react";

import AppShell from "@/components/AppShell";
import {
  MENTOR_ID_LIMIT,
  assignmentSummary,
  validMentorId,
  validStudentId,
} from "@/lib/admin";
import { ApiError, assignMentor } from "@/lib/api";

function AssignForm() {
  const [studentId, setStudentId] = useState("");
  const [mentorId, setMentorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const valid = validStudentId(studentId) && validMentorId(mentorId);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await assignMentor(Number(studentId), mentorId);
      setNotice(`Student ${result.student_id}: ${assignmentSummary(result)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} aria-labelledby="assign">
      <h2 id="assign">Assign a mentor</h2>
      <p className="muted">
        Sets the mentor for one student. If the student has an open case, it
        moves to the new mentor. For many students at once, use the
        mentor_assignments.csv import.
      </p>
      <label htmlFor="student">Student ID</label>
      <input
        id="student"
        type="number"
        min={1}
        inputMode="numeric"
        value={studentId}
        onChange={(e) => setStudentId(e.target.value)}
      />
      <label htmlFor="mentor">Mentor ID</label>
      <input
        id="mentor"
        type="text"
        maxLength={MENTOR_ID_LIMIT + 1}
        autoComplete="off"
        value={mentorId}
        onChange={(e) => setMentorId(e.target.value)}
      />
      <p className="muted small">
        Exactly as the mentor signs in (M1 and m1 are different).
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button type="submit" disabled={busy || !valid}>
        Save assignment
      </button>
    </form>
  );
}

export default function AssignmentsPage() {
  return (
    <AppShell roles={["admin"]} title="Mentor assignments">
      <AssignForm />
    </AppShell>
  );
}
