export const SHOWN_TIME_ZONE = "Asia/Seoul";
const TIME = new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: SHOWN_TIME_ZONE });
const TIME_SECONDS = new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: SHOWN_TIME_ZONE });
const DATE = new Intl.DateTimeFormat("sv-SE", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: SHOWN_TIME_ZONE });
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

const HANGUL_FIRST = 0xac00;
const HANGUL_LAST = 0xd7a3;
const RIEUL_FINAL = 8;
const DIGITS_TAKING_EURO = new Set(["0", "3", "6"]);

export function ro(word: string): string {
  const last = word.trim().slice(-1);
  const code = last.charCodeAt(0);
  if (code >= HANGUL_FIRST && code <= HANGUL_LAST) {
    const final = (code - HANGUL_FIRST) % 28;
    return final === 0 || final === RIEUL_FINAL ? "로" : "으로";
  }
  return DIGITS_TAKING_EURO.has(last) ? "으로" : "로";
}
