import type { Side } from "./panes/types";

export const to = {
  home: () => "/",
  login: (next?: string) => (next && next !== "/" && !next.startsWith("/login") ? `/login?next=${encodeURIComponent(next)}` : "/login"),
  signup: () => "/signup",
  access: () => "/access",
  records: () => "/records",
  record: (record: number) => `/records/${record}`,
  debrief: (round: number) => `/rounds/${round}/debrief`,
  allocation: (allocation: number) => `/allocations/${allocation}`,
  player: (round: number, side: Side) => `/rounds/${round}/${side}`,
  result: (round: number, side?: string) => `/rounds/${round}/result${side ? `?side=${side}` : ""}`,
  staffProblems: () => "/staff/problems",
  staffProblem: (id: number) => `/staff/problems/${id}`,
  staffPostures: () => "/staff/postures",
  staffUsers: () => "/staff/users",
  staffRange: () => "/staff/range",
};
