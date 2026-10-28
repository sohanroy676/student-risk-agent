// A stand-in for the API at the network layer, so the screens can be tested without a backend.
// It follows the same rules the real one does for the moves these tests make; the real rules
// are tested in the Python suite.

import type { Page, Route } from "@playwright/test";

import type {
  CaseDetail,
  CaseState,
  Concern,
  GateResult,
  ModelRelease,
  Role,
} from "../lib/types";

export interface Recorded {
  method: string;
  path: string;
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
  private failure: { status: number; detail: unknown } | null = null;
  /** The model registry the admin screens read; set it in a test that needs one. */
  releases: ModelRelease[] = [];
  /** The concerns the signed-in role may see (the real API narrows them by row security). */
  concerns: Concern[] = [];

  constructor(
    readonly cases: CaseDetail[],
    private readonly role: Role = "mentor",
  ) {}

  /** The next request that reaches the API gets this error instead of an answer. */
  failNext(status: number, detail: unknown): void {
    this.failure = { status, detail };
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
    this.requests.push({ method: request.method(), path, body });

    if (this.failure) {
      const { status, detail } = this.failure;
      this.failure = null;
      return this.reply(route, status, { detail });
    }
    if (request.method() === "GET" && path === "/api/caseload") {
      const items = this.cases.filter((c) => OPEN.includes(c.state));
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
