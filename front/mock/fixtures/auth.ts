import { refuse, reply, type Fixture } from "../fixture";

const SIGNED_OUT_VARIANTS = ["signed-out", "wrong-password", "pending", "too-many", "username-taken", "weak-password"];
const BACK_TO_SIGNED_IN = { "Set-Cookie": "mock_variant=; Path=/; Max-Age=0" };

function signedOutMe(variant: string): Fixture {
  return refuse("get", "/api/me/", 401, [{ path: "", code: "not_signed_in" }], { variant });
}

function signInFromSignedOut(): Fixture {
  return {
    method: "post",
    path: "/api/auth/login/",
    variant: "signed-out",
    answer: (asked) => ({
      status: 200,
      body: { user: (asked.body as { username?: string } | undefined)?.username ?? "learner-one" },
      headers: BACK_TO_SIGNED_IN,
    }),
  };
}

export const fixtures = [
  reply("get", "/api/auth/csrf/", { ok: true }),
  reply("get", "/api/me/", { user: "learner-one", is_staff: true, approved: true, site_origin: "http://localhost:8002" }),
  ...SIGNED_OUT_VARIANTS.map(signedOutMe),
  reply("get", "/api/me/", { user: "learner-two", is_staff: false, approved: true, site_origin: "http://localhost:8002" }, { variant: "learner" }),
  reply("post", "/api/auth/login/", (asked) => ({ user: asked.body?.username ?? "learner-one" })),
  signInFromSignedOut(),
  refuse("post", "/api/auth/login/", 400, [{ path: "", code: "wrong_credentials" }], { variant: "wrong-password" }),
  refuse("post", "/api/auth/login/", 403, [{ path: "", code: "account_pending" }], { variant: "pending" }),
  refuse("post", "/api/auth/login/", 429, [{ path: "", code: "too_many" }], { variant: "too-many" }),
  reply("post", "/api/auth/logout/", undefined, { status: 204 }),
  reply("post", "/api/auth/signup/", (asked) => ({ user: asked.body?.username ?? "new-learner", approved: false }), { status: 201 }),
  refuse("post", "/api/auth/signup/", 400, [{ path: "username", code: "username_taken" }], { variant: "username-taken" }),
  refuse("post", "/api/auth/signup/", 400, [
    { path: "password", code: "password_too_short", params: { min_length: 8 } },
    { path: "password", code: "password_entirely_numeric" },
  ], { variant: "weak-password" }),
];
