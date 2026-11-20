export type Side = "attack" | "defence";

export type Placement = "main" | "aside" | "aside-lead";

export interface PaneProps {
  round: number;
  side: Side;
  placement: Placement;
}
