import type { Answer, Fixture } from "../fixture";
import { minutesFromNow, reply } from "../fixture";

interface MockStep {
  order: number;
  opens: string;
  hints: string[];
  asksText: boolean;
}

const steps: MockStep[] = [
  { order: 1, opens: "terminal_kali", hints: ["Placeholder hint 1.1"], asksText: false },
  { order: 2, opens: "kibana", hints: ["Placeholder hint 2.1", "Placeholder hint 2.2"], asksText: true },
  { order: 3, opens: "terminal_kali", hints: [], asksText: false },
  { order: 4, opens: "alerts", hints: ["Placeholder hint 4.1", "Placeholder hint 4.2", "Placeholder hint 4.3"], asksText: false },
  { order: 5, opens: "ids_rules", hints: ["Placeholder hint 5.1"], asksText: false },
  { order: 6, opens: "ids_rules", hints: [], asksText: false },
];

const START_PASSED = 3;
const progress = { passed: START_PASSED, ended: false };

const problem = { id: 5, side: "defence", title: "Board lesson placeholder", summary: "Placeholder summary", body: "Placeholder body" };

function phaseFor(variant: string) {
  if (variant === "lesson-waiting") return "waiting_slot" as const;
  if (variant === "lesson-starting") return "starting" as const;
  return progress.ended || progress.passed >= steps.length ? ("ended" as const) : ("ready" as const);
}

function shown(round: number, variant: string) {
  if (variant === "lesson-reset") {
    progress.passed = START_PASSED;
    progress.ended = false;
  }
  const phase = phaseFor(variant);
  return {
    round,
    lease: 6,
    phase,
    problem,
    steps: steps.map((step) => ({ order: step.order, body: `Placeholder step ${step.order} body`, opens: step.opens, hints_available: step.hints.length })),
    current: phase === "ended" ? null : progress.passed + 1,
    progress: { passed_order: progress.passed, passed_at: progress.passed > 0 ? minutesFromNow(-3) : null },
  };
}

function refused(status: number, code: string, path = "", params?: Record<string, unknown>): Answer {
  return { status, body: { errors: [{ path, code, ...(params ? { params } : {}) }] } };
}

function verdict(passed: boolean, detail: string | null, next: number | null): Answer {
  return { status: 200, body: { verdict: passed ? "passed" : "not_yet", detail_code: detail, next } };
}

const check: Fixture = {
  method: "post",
  path: "/api/lessons/{round_id}/steps/{order}/check/",
  answer: (asked) => {
    const order = Number(asked.params.order);
    const step = steps.find((one) => one.order === order);
    if (!step) return refused(404, "unknown_step");
    if (order > progress.passed + 1) return refused(409, "step_locked");
    const answer = (asked.body as { answer?: unknown } | undefined)?.answer;
    if (step.asksText && !answer) return verdict(false, "no_answer", null);
    if (asked.variant === "not-yet") return verdict(false, "no_alert", null);
    if (order === progress.passed + 1) progress.passed = order;
    return verdict(true, null, order < steps.length ? order + 1 : null);
  },
};

const hint: Fixture = {
  method: "post",
  path: "/api/lessons/{round_id}/steps/{order}/hint/",
  answer: (asked) => {
    const step = steps.find((one) => one.order === Number(asked.params.order));
    if (!step) return refused(404, "unknown_step");
    const n = Number((asked.body as { n?: number } | undefined)?.n ?? 1);
    const text = step.hints[n - 1];
    if (!text) return refused(400, "max_value", "n", { max: step.hints.length });
    return { status: 200, body: { hint: text, n, left: step.hints.length - n } };
  },
};

export const fixtures: Fixture[] = [
  reply("get", "/api/lessons/{round_id}/", (asked) => shown(Number(asked.params.round_id), asked.variant)),
  check,
  hint,
  reply("post", "/api/lessons/{round_id}/end/", () => {
    progress.ended = true;
    return { ended: new Date().toISOString() };
  }),
];
