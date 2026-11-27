const TIME = new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
const TIME_SECONDS = new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const DATE = new Intl.DateTimeFormat("sv-SE", { year: "numeric", month: "2-digit", day: "2-digit" });
const NUMBER = new Intl.NumberFormat("ko-KR");

export function clock(at: string | null | undefined): string {
  return at ? TIME.format(new Date(at)) : "";
}

export function clockSeconds(at: string | null | undefined): string {
  return at ? TIME_SECONDS.format(new Date(at)) : "";
}

export function day(at: string | null | undefined): string {
  return at ? DATE.format(new Date(at)) : "";
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : NUMBER.format(value);
}

export interface TitledCase {
  case: string;
  title?: string | null;
}

export function caseLabel(line: TitledCase): string {
  return line.title || line.case;
}
