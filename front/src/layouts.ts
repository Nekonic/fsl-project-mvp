import type { IconName } from "./ui";
import type { StringKey } from "./strings";
import type { PaneId } from "./panes/registry";
import type { Side } from "./panes/types";

export interface RailEntry {
  pane: PaneId;
  label: StringKey;
  icon: IconName;
  beside?: PaneId[];
}

export interface ConsoleSpec {
  side: Side;
  mark: "attack" | "defence" | "lesson";
  rail: RailEntry[];
  asideLead?: PaneId;
  aside: PaneId[];
  railAlways?: PaneId[];
}

const kibana: RailEntry = { pane: "kibana", label: "pane.kibana", icon: "search" };
const map: RailEntry = { pane: "map", label: "pane.map", icon: "map" };
const idsRules: RailEntry = { pane: "ids_rules", label: "pane.ids_rules", icon: "rules" };
const waf: RailEntry = { pane: "waf", label: "pane.waf", icon: "shield" };
const alerts: RailEntry = { pane: "alerts", label: "pane.alerts", icon: "bell" };
const terminalWaf: RailEntry = { pane: "terminal_waf", label: "pane.terminal_waf", icon: "terminal" };
const terminalKali: RailEntry = { pane: "terminal_kali", label: "pane.terminal_kali", icon: "terminal" };
const site: RailEntry = { pane: "site", label: "pane.site", icon: "globe" };
const loot: RailEntry = { pane: "loot", label: "pane.loot", icon: "upload" };

export type LayoutName = "attack" | "defence" | "lesson";

export const layouts: Record<LayoutName, ConsoleSpec> = {
  attack: {
    side: "attack",
    mark: "attack",
    rail: [terminalKali, site, loot],
    asideLead: "hp",
    aside: ["objectives", "loot", "cases"],
  },
  defence: {
    side: "defence",
    mark: "defence",
    rail: [kibana, map, idsRules, waf, alerts, terminalWaf],
    asideLead: "objectives",
    aside: ["applied"],
  },
  lesson: {
    side: "defence",
    mark: "lesson",
    rail: [{ ...terminalKali, label: "pane.kali" }, kibana, alerts, idsRules, waf, map, site, terminalWaf],
    asideLead: "step_card",
    aside: ["hp"],
    railAlways: ["map"],
  },
};
