import type { FunctionComponent } from "preact";
import { Alerts } from "./Alerts";
import { AttackCases } from "./AttackCases";
import { Brief } from "./Brief";
import { Origins } from "./Origins";
import { IdsRules } from "./IdsRules";
import { Kibana } from "./Kibana";
import { Loot } from "./Loot";
import { MapPane } from "./Map";
import { Objectives } from "./Objectives";
import { RuleVersions } from "./RuleVersions";
import { Site } from "./Site";
import { TerminalDefence, TerminalKali } from "./Terminal";
import type { PaneProps } from "./types";
import { Waf } from "./Waf";

export const panes = {
  kibana: Kibana,
  terminal_kali: TerminalKali,
  terminal_defence: TerminalDefence,
  site: Site,
  map: MapPane,
  ids_rules: IdsRules,
  waf: Waf,
  alerts: Alerts,
  loot: Loot,
  objectives: Objectives,
  origins: Origins,
  cases: AttackCases,
  applied: RuleVersions,
  brief: Brief,
} satisfies Record<string, FunctionComponent<PaneProps>>;

export type PaneId = keyof typeof panes;

export function isPaneId(id: string): id is PaneId {
  return Object.prototype.hasOwnProperty.call(panes, id);
}
