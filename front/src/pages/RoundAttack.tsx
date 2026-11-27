import { Console } from "../console/Console";
import { RoundHeader } from "../console/RoundHeader";
import { layouts } from "../layouts";
import { OriginsSpentBanner, useAttackState } from "../panes/Origins";
import type { PageProps } from "../routes";
import { t } from "../strings";

export function RoundAttack({ params }: PageProps) {
  const round = Number(params.round);
  const state = useAttackState(round);
  const lootTaken = state.data?.takes_loot === true;
  const spec = layouts.attack;
  return (
    <Console
      spec={spec}
      round={round}
      title={t("page.attack")}
      rail={lootTaken ? spec.rail : spec.rail.filter((entry) => entry.pane !== "loot")}
      aside={lootTaken ? spec.aside : spec.aside.filter((pane) => pane !== "loot")}
      header={<><RoundHeader round={round} side="attack" /><OriginsSpentBanner round={round} /></>}
    />
  );
}
