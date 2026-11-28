import { hasString, t } from "./strings";

function shown(key: string): string {
  return hasString(key) ? t(key) : "";
}

export function wargameName(wargame: string): string {
  return shown(`wargame.${wargame}`) || wargame;
}

export function wargameLead(wargame: string): string {
  return shown(`wargame.${wargame}.lead`);
}

export function wargameHost(wargame: string): string {
  return shown(`wargame.${wargame}.host`);
}
