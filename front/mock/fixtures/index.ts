import type { Fixture } from "../fixture";

const groups = import.meta.glob<{ fixtures: Fixture[] }>(["./*.ts", "!./index.ts"], { eager: true });

export const fixtures: Fixture[] = Object.keys(groups).sort().flatMap((name) => groups[name]?.fixtures ?? []);
