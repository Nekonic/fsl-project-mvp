import { Console } from "../console/Console";
import { RoundHeader } from "../console/RoundHeader";
import { layouts } from "../layouts";
import { OriginsSpentBanner } from "../panes/Origins";
import type { PageProps } from "../routes";
import { t } from "../strings";

export function RoundAttack({ params }: PageProps) {
  const round = Number(params.round);
  return (
    <Console
      spec={layouts.attack}
      round={round}
      title={t("page.attack")}
      header={<><RoundHeader round={round} side="attack" /><OriginsSpentBanner round={round} /></>}
    />
  );
}
