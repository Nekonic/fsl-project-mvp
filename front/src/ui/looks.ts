import type { BadgeTone } from "./Badge";
import type { IconName } from "./Icon";
import type { TileTone } from "./Tiles";

export interface TileLook {
  icon: IconName;
  tone: TileTone;
}

export const roundTileLook: TileLook = { icon: "swords", tone: "red" };

const PHASE_TONE: Record<string, BadgeTone> = { running: "ok", ended: "muted" };

export function phaseTone(phase: string): BadgeTone {
  return PHASE_TONE[phase] ?? "warn";
}
