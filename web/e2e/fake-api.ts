// A stand-in for the API at the network layer, so the screens can be tested without a backend.
// It follows the same rules the real one does for the moves these tests make; the real rules
// are tested in the Python suite.

import type { Page, Route } from "@playwright/test";

import type {
  AuditCheck,
  AuditEntry,
  CaseDetail,
  CaseState,
  Concern,
  GateResult,
  ModelRelease,
  NightlyRun,
  Overview,
  Role,
} from "../lib/types";

export interface Recorded {
  method: string;
  path: string;
  query: string; // the part after the ?, if any
  body: unknown;
}

function base64url(value: object): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

/** An unsigned token. Fine here: the app only reads the role, and the API is faked. */
export function tokenFor(
  role: Role | string,
  options: { sub?: string; exp?: number } = {},
): string {
  const exp = options.exp ?? Math.floor(Date.now() / 1000) + 3600;
  return `${base64url({ alg: "none" })}.${base64url({ sub: options.sub ?? "m1", roles: [role], exp })}.x`;
}

export async function signIn(
  page: Page,
  role: Role,
  sub = "m1",
): Promise<void> {
  const token = tokenFor(role, { sub });
  // Only on the first load of the tab: a later full reload (after a sign-out) must stay signed out.
  await page.addInitScript((value) => {
    if (window.sessionStorage.getItem("test.signed-in")) return;
    window.sessionStorage.setItem("test.signed-in", "1");
    window.sessionStorage.setItem("sra.token", value);
  }, token);
}

/** The app's own alert; Next also keeps an empty route announcer with role=alert in the body. */
export function appAlert(page: Page) {
  return page.locator("main").getByRole("alert");
}

export function makeCase(
  id: number,
  overrides: Partial<CaseDetail> = {},
): CaseDetail {
  return {
    id,
    student_id: id * 10,
    mentor_id: "m1",
    state: "drafted",
    band: "red",
    reason: "red",
    cycle: 1,
    opened_on: "2026-03-01",
    entered_on: "2026-03-02",
    due_on: "2026-03-05",
    overdue: false,
    approved_by: null,
    approved_on: null,
    timeline: [
      {
        on_date: "2026-03-01",
        kind: "opened",
        from_state: null,
        to_state: "new",
        actor_kind: "system",
        actor_id: null,
        detail: { reason: "red" },
      },
    ],
    reasons: [
      {
        rank: 1,
        fact_id: `case-${id}/attendance_rate/2026-03-02`,
        feature: "attendance_rate",
        text: "Attendance is 40% so far",
      },
    ],
    draft: {
      version: 1,
      source: "template",
      author: "template",
      created_on: "2026-03-02",
      message: "Hi, how are you getting on?",
    },
    ...overrides,
  };
}

const OPEN: CaseState[] = [
  "new",
  "drafted",
  "monitoring",
  "in_review",
  "escalated",
];

export class FakeApi {
  readonly requests: Recorded[] = [];
  private failure: { status: number; detail: unknown; left: number } | null =
    null;
  /** The model registry the admin screens read; set it in a test that needs one. */
  releases: ModelRelease[] = [];
  /** The concerns the signed-in role may see (the real API narrows them by row security). */
  concerns: Concern[] = [];
  /** The latest nightly run; null means none is recorded (404). */
  nightlyRun: NightlyRun | null = null;
  /** Mentor per student id as set through the assignment endpoint (student 999 is unknown). */
  readonly assignments = new Map<number, string>();
  /** Students with no mentor, as the overview reports them. */
  unassigned = 0;
  /** Audit entries, oldest first; the fake serves them newest first like the API. */
  auditLog: AuditEntry[] = [];
  /** What the chain check answers. */
  auditCheck: AuditCheck = {
    ok: true,
    checked: 0,
    first_bad_seq: null,
    problem: null,
    anchor: null,
  };

  constructor(
    readonly cases: CaseDetail[],
    private readonly role: Role = "mentor",
  ) {}

  /**
   * The next `times` requests that reach the API get this error instead of an answer. A page
   * that loads data in an effect asks twice under the dev server (React Strict Mode), so a test
   * that must see the error on load passes 2.
   */
  failNext(status: number, detail: unknown, times = 1): void {
    this.failure = { status, detail, left: times };
  }

  calls(method: string, pathPrefix: string): Recorded[] {
    return this.requests.filter(
      (r) => r.method === method && r.path.startsWith(pathPrefix),
    );
  }

  async install(page: Page): Promise<void> {
    await page.route("**/backend/**", (route) => this.handle(route));
  }

  private reply(route: Route, status: number, body: unknown) {
    return route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  }

  private async handle(route: Route) {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/backend/, "");
    const raw = request.postData();
    const body: unknown = raw ? JSON.parse(raw) : null;
    this.requests.push({
      method: request.method(),
      path,
      query: url.search.replace(/^\?/, ""),
      body,
    });

    if (this.failure) {
      const { status, detail } = this.failure;
      this.failure =
        this.failure.left > 1
          ? { ...this.failure, left: this.failure.left - 1 }
          : null;
      return this.reply(route, status, { detail });
    }
    if (request.method() === "GET" && path === "/api/caseload") {
      const wanted = url.searchParams.get("state");
      const items = this.cases.filter((c) =>
        wanted ? c.state === wanted : OPEN.includes(c.state),
      );
      return this.reply(route, 200, {
        items,
        total: items.length,
        limit: 50,
        offset: 0,
      });
    }
    const concern = /^\/api\/concerns(?:\/(\d+)\/acknowledge)?$/.exec(path);
    if (concern) {
      return this.concernRoute(route, request.method(), concern[1], url, body);
    }
    if (request.method() === "GET" && path === "/api/overview") {
      if (this.role !== "staff" && this.role !== "admin")
        return this.reply(route, 403, { detail: "not allowed" });
      return this.reply(route, 200, this.overview());
    }
    if (request.method() === "GET" && path === "/api/admin/audit/verify") {
      return this.reply(route, 200, this.auditCheck);
    }
    if (request.method() === "GET" && path === "/api/admin/audit") {
      const wanted = url.searchParams.get("action");
      const limit = Number(url.searchParams.get("limit") ?? 50);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const rows = this.auditLog
        .filter((e) => !wanted || e.action === wanted)
        .reverse();
      return this.reply(route, 200, {
        items: rows.slice(offset, offset + limit),
        total: rows.length,
        limit,
        offset,
      });
    }
    const assign = /^\/api\/admin\/mentor-assignments\/(\d+)$/.exec(path);
    if (assign && request.method() === "PUT") {
      const studentId = Number(assign[1]);
      if (studentId === 999)
        return this.reply(route, 404, { detail: "student not found" });
      const { mentor_id } = body as { mentor_id: string };
      const changed = this.assignments.get(studentId) !== mentor_id;
      this.assignments.set(studentId, mentor_id);
      const open = this.cases.filter(
        (c) =>
          c.student_id === studentId &&
          OPEN.includes(c.state) &&
          c.mentor_id !== mentor_id,
      );
      for (const c of open) c.mentor_id = mentor_id;
      return this.reply(route, 200, {
        student_id: studentId,
        changed,
        cases_moved: open.length,
      });
    }
    if (request.method() === "GET" && path === "/api/admin/nightly/latest") {
      return this.nightlyRun
        ? this.reply(route, 200, this.nightlyRun)
        : this.reply(route, 404, { detail: "no nightly run recorded" });
    }
    const models = /^\/api\/admin\/models(?:\/(\d+))?(\/card|\/promote)?$/.exec(
      path,
    );
    if (models) return this.models(route, request.method(), models, body);
    const match = /^\/api\/cases\/(\d+)(\/actions|\/draft)?$/.exec(path);
    const found = match
      ? this.cases.find((c) => c.id === Number(match[1]))
      : undefined;
    if (!match || !found)
      return this.reply(route, 404, { detail: "case not found" });

    if (request.method() === "GET" && !match[2]) {
      return this.reply(
        route,
        200,
        found.reasons.length && this.role === "admin"
          ? { ...found, reasons: [], draft: null }
          : found,
      );
    }
    if (request.method() === "POST" && match[2] === "/actions") {
      const action = (body as { action: string }).action;
      if (action === "approve") {
        if (found.state !== "drafted")
          return this.reply(route, 409, { detail: "cannot approve" });
        found.state = "monitoring";
        found.approved_by = "m1";
        found.approved_on = "2026-03-03";
      } else if (action === "dismiss") {
        found.state = "dismissed";
      } else if (action === "continue" && found.state === "in_review") {
        found.state = "monitoring";
        found.cycle += 1;
      } else if (action === "resolve") {
        found.state = "resolved";
      } else if (action === "escalate") {
        found.state = "escalated";
      }
      return this.reply(route, 200, { id: found.id, state: found.state });
    }
    if (request.method() === "PUT" && match[2] === "/draft") {
      const message = (body as { message: string }).message.trim();
      const version = (found.draft?.version ?? 0) + 1;
      found.draft = {
        version,
        source: "mentor",
        author: "m1",
        created_on: "2026-03-03",
        message,
      };
      return this.reply(route, 200, { id: found.id, version });
    }
    return this.reply(route, 405, { detail: "method not allowed" });
  }

  /** Counts of the open cases the fake holds, shaped like GET /api/overview. */
  private overview(): Overview {
    const open = this.cases.filter((c) => OPEN.includes(c.state));
    const by_state = Object.fromEntries(OPEN.map((s) => [s, 0]));
    const by_band = { amber: 0, red: 0 };
    const mentors = new Map<string, { open: number; overdue: number }>();
    for (const c of open) {
      by_state[c.state] += 1;
      by_band[c.band] += 1;
      const m = mentors.get(c.mentor_id) ?? { open: 0, overdue: 0 };
      m.open += 1;
      if (c.overdue) m.overdue += 1;
      mentors.set(c.mentor_id, m);
    }
    return {
      open_cases: open.length,
      overdue: open.filter((c) => c.overdue).length,
      by_state,
      by_band,
      by_mentor: [...mentors].map(([mentor_id, m]) => ({ mentor_id, ...m })),
      unassigned_students: this.unassigned,
    };
  }

  private concernRoute(
    route: Route,
    method: string,
    acknowledgeId: string | undefined,
    url: URL,
    body: unknown,
  ) {
    if (acknowledgeId) {
      const found = this.concerns.find((c) => c.id === Number(acknowledgeId));
      if (!found)
        return this.reply(route, 404, { detail: "concern not found" });
      if (found.acknowledged) {
        return this.reply(route, 409, {
          detail: "concern already acknowledged",
        });
      }
      Object.assign(found, {
        acknowledged: true,
        acknowledged_by: "m1",
        acknowledged_on: "2026-03-03",
      });
      return this.reply(route, 200, found);
    }
    if (method === "POST") {
      const { student_id, category, note } = body as {
        student_id: number;
        category: Concern["category"];
        note: string;
      };
      if (student_id === 999) {
        return this.reply(route, 404, { detail: "student not found" });
      }
      const id = this.concerns.length + 1;
      this.concerns.unshift({
        id,
        student_id,
        category,
        raised_on: "2026-03-03",
        note,
        acknowledged: false,
        raised_by: null,
        acknowledged_by: null,
        acknowledged_on: null,
      });
      return this.reply(route, 200, { id });
    }
    const openOnly = url.searchParams.get("open_only") === "true";
    const items = this.concerns.filter((c) => !openOnly || !c.acknowledged);
    return this.reply(route, 200, {
      items,
      total: items.length,
      limit: 50,
      offset: 0,
    });
  }

  private models(
    route: Route,
    method: string,
    match: RegExpExecArray,
    body: unknown,
  ) {
    if (!match[1]) {
      return method === "GET"
        ? this.reply(route, 200, this.releases)
        : this.reply(route, 405, { detail: "method not allowed" });
    }
    const release = this.releases.find((r) => r.release === Number(match[1]));
    if (!release)
      return this.reply(route, 404, { detail: "release not found" });
    if (method === "GET" && !match[2]) return this.reply(route, 200, release);
    if (method === "GET" && match[2] === "/card") {
      return this.reply(route, 200, {
        release: release.release,
        markdown: `# Model card: release ${release.release}

<b>not html</b>`,
      });
    }
    if (method === "POST" && match[2] === "/promote") {
      const { covers } = body as { reason: string; covers: string[] };
      const gate = release.gate_now;
      if (release.in_production || !gate) {
        return this.reply(route, 409, {
          detail: "release is already in production",
        });
      }
      const unresolved = gate.blocks.filter((b) => !covers.includes(b));
      if (unresolved.length > 0 || gate.hard_failures.length > 0) {
        return this.reply(route, 409, {
          detail: { unresolved, hard_failures: gate.hard_failures },
        });
      }
      for (const r of this.releases) r.in_production = r === release;
      release.gate_now = null;
      const result: GateResult = {
        passed: true,
        blocks: gate.blocks,
        hard_failures: [],
        overridden: covers,
        signed_off_by: "root",
      };
      return this.reply(route, 200, result);
    }
    return this.reply(route, 405, { detail: "method not allowed" });
  }
}

export function makeRelease(
  release: number,
  overrides: Partial<ModelRelease> = {},
): ModelRelease {
  return {
    release,
    created: "2026-03-01T10:00:00+00:00",
    weeks: [1, 2, 4, 6, 8],
    in_production: false,
    metrics: {
      auc_week4: 0.74,
      ece: 0.02,
      recall_gaps: { gender: 0.03, region: 0.04 },
    },
    gate_now: {
      passed: true,
      blocks: [],
      hard_failures: [],
      overridden: [],
      signed_off_by: null,
    },
    gate_recorded: null,
    sign_off: null,
    ...overrides,
  };
}

export function blockedBy(...blocks: string[]): ModelRelease["gate_now"] {
  return {
    passed: false,
    blocks,
    hard_failures: [],
    overridden: [],
    signed_off_by: null,
  };
}

export function makeConcern(
  id: number,
  overrides: Partial<Concern> = {},
): Concern {
  return {
    id,
    student_id: id * 10,
    category: "attendance",
    raised_on: "2026-03-02",
    note: "Missed three labs in a row",
    acknowledged: false,
    raised_by: "f1",
    acknowledged_by: null,
    acknowledged_on: null,
    ...overrides,
  };
}
