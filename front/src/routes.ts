import type { FunctionComponent } from "preact";
import { Home } from "./pages/Home";
import { Lesson } from "./pages/Lesson";
import { Login } from "./pages/Login";
import { Result } from "./pages/Result";
import { RoundAttack } from "./pages/RoundAttack";
import { RoundDefence } from "./pages/RoundDefence";
import { RoundLobby } from "./pages/RoundLobby";
import { Signup } from "./pages/Signup";
import { Postures } from "./pages/staff/Postures";
import { Problems } from "./pages/staff/Problems";
import { Range } from "./pages/staff/Range";
import { Users } from "./pages/staff/Users";
import { matched, type Params } from "./router";

export interface PageProps {
  params: Params;
}

export type Access = "public" | "member" | "staff";

export interface Route {
  path: string;
  page: FunctionComponent<PageProps>;
  access: Access;
}

export const routes: Route[] = [
  { path: "/login", page: Login, access: "public" },
  { path: "/signup", page: Signup, access: "public" },
  { path: "/", page: Home, access: "member" },
  { path: "/leases/:lease", page: RoundLobby, access: "member" },
  { path: "/lessons/:round", page: Lesson, access: "member" },
  { path: "/rounds/:round/attack", page: RoundAttack, access: "member" },
  { path: "/rounds/:round/defence", page: RoundDefence, access: "member" },
  { path: "/rounds/:round/result", page: Result, access: "member" },
  { path: "/staff/problems", page: Problems, access: "staff" },
  { path: "/staff/problems/:id", page: Problems, access: "staff" },
  { path: "/staff/postures", page: Postures, access: "staff" },
  { path: "/staff/users", page: Users, access: "staff" },
  { path: "/staff/range", page: Range, access: "staff" },
];

export interface Resolved {
  route: Route;
  params: Params;
}

export function resolve(path: string): Resolved | null {
  for (const route of routes) {
    const params = matched(route.path, path);
    if (params) return { route, params };
  }
  return null;
}
