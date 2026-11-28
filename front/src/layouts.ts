import type { IconName } from "./ui";
import type { StringKey } from "./strings";
import type { PaneId } from "./panes/registry";
import type { Side } from "./panes/types";

export interface RailEntry {
  pane: PaneId;
  label: StringKey;
  icon: IconName;
}

export interface ConsoleSpec {
  side: Side;
  rail: RailEntry[];
  asideLead?: PaneId;
  aside: PaneId[];
}

const kibana: RailEntry = { pane: "kibana", label: "pane.kibana", icon: "search" };
const map: RailEntry = { pane: "map", label: "pane.map", icon: "map" };
const idsRules: RailEntry = { pane: "ids_rules", label: "pane.ids_rules", icon: "rules" };
const waf: RailEntry = { pane: "waf", label: "pane.waf", icon: "shield" };
const alerts: RailEntry = { pane: "alerts", label: "pane.alerts", icon: "bell" };
const terminalDefence: RailEntry = { pane: "terminal_defence", label: "pane.terminal_defence", icon: "terminal" };
const terminalKali: RailEntry = { pane: "terminal_kali", label: "pane.terminal_kali", icon: "terminal" };
const site: RailEntry = { pane: "site", label: "pane.site", icon: "globe" };
const loot: RailEntry = { pane: "loot", label: "pane.loot", icon: "upload" };

export const layouts: Record<Side, ConsoleSpec> = {
  attack: {
    side: "attack",
    rail: [terminalKali, site, loot],
    asideLead: "origins",
    aside: ["brief", "objectives", "loot", "cases"],
  },
  defence: {
    side: "defence",
    rail: [alerts, kibana, map, idsRules, waf, terminalDefence],
    asideLead: "objectives",
    aside: ["brief", "applied"],
  },
};
