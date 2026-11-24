import { to } from "./links";
import type { StringKey } from "./strings";

export interface NavEntry {
  href: string;
  label: StringKey;
  staff: boolean;
}

export const topNav: NavEntry[] = [
  { href: to.records(), label: "nav.records", staff: false },
  { href: to.access(), label: "nav.access", staff: false },
  { href: to.staffProblems(), label: "nav.staff.problems", staff: true },
  { href: to.staffPostures(), label: "nav.staff.postures", staff: true },
  { href: to.staffUsers(), label: "nav.staff.users", staff: true },
  { href: to.staffRange(), label: "nav.staff.range", staff: true },
];

export const signOutLabel: StringKey = "auth.sign_out";
export const brandLabel: StringKey = "brand";
export const homeCrumb: StringKey = "nav.home";
