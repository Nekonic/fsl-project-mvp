import type { BadgeTone } from "./Badge";
import type { IconName } from "./Icon";
import type { TileTone } from "./Tiles";

export interface TileLook {
  icon: IconName;
  tone: TileTone;
}

const LESSON_TILE_LOOKS: TileLook[] = [
  { icon: "map", tone: "blue" },
  { icon: "code", tone: "violet" },
  { icon: "search", tone: "green" },
  { icon: "rules", tone: "pink" },
  { icon: "terminal", tone: "orange" },
  { icon: "shield", tone: "cyan" },
];

export const roundTileLook: TileLook = { icon: "swords", tone: "red" };

export function lessonTileLook(lessonNo: number): TileLook {
  return LESSON_TILE_LOOKS[(Math.max(lessonNo, 1) - 1) % LESSON_TILE_LOOKS.length] as TileLook;
}

const PHASE_TONE: Record<string, BadgeTone> = { running: "ok", ended: "muted" };

export function phaseTone(phase: string): BadgeTone {
  return PHASE_TONE[phase] ?? "warn";
}
