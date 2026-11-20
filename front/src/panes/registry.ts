import type { FunctionComponent } from "preact";
import { Alerts } from "./Alerts";
import { AttackCases } from "./AttackCases";
import { Hp } from "./Hp";
import { IdsRules } from "./IdsRules";
import { Kibana } from "./Kibana";
import { Loot } from "./Loot";
import { MapPane } from "./Map";
import { Objectives } from "./Objectives";
import { RuleVersions } from "./RuleVersions";
import { Score } from "./Score";
import { Site } from "./Site";
import { StepCard } from "./StepCard";
import { TerminalKali, TerminalWaf } from "./Terminal";
import type { PaneProps } from "./types";
import { Waf } from "./Waf";

export const panes = {
  kibana: Kibana,
  terminal_kali: TerminalKali,
  terminal_waf: TerminalWaf,
  site: Site,
  map: MapPane,
  ids_rules: IdsRules,
  waf: Waf,
  alerts: Alerts,
  loot: Loot,
  objectives: Objectives,
  hp: Hp,
  cases: AttackCases,
  applied: RuleVersions,
  step_card: StepCard,
  score: Score,
} satisfies Record<string, FunctionComponent<PaneProps>>;

export type PaneId = keyof typeof panes;

export function isPaneId(id: string): id is PaneId {
  return Object.prototype.hasOwnProperty.call(panes, id);
}
