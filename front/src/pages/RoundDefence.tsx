import { Console } from "../console/Console";
import { RoundHeader } from "../console/RoundHeader";
import { layouts } from "../layouts";
import { LimitBelowFloorBanner } from "../panes/Origins";
import { VerdictNotices } from "../panes/Verdicts";
import type { PageProps } from "../routes";
import { t } from "../strings";

export function RoundDefence({ params }: PageProps) {
  const round = Number(params.round);
  return <Console spec={layouts.defence} round={round} title={t("page.defence")} header={<><RoundHeader round={round} side="defence" /><LimitBelowFloorBanner round={round} /><VerdictNotices round={round} /></>} />;
}
