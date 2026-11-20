import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import type { ConsoleSpec, RailEntry } from "../layouts";
import { setHash, usePlace } from "../router";
import { t } from "../strings";
import { Aside, ConsoleLayout, KeptPane, PaneSplit, Rail, type Crumb } from "../ui";
import { AppPage } from "../shell/AppPage";
import { isPaneId, panes, type PaneId } from "../panes/registry";
import type { Placement, Side } from "../panes/types";

export interface ConsoleProps {
  spec: ConsoleSpec;
  round: number;
  side?: Side;
  title: string;
  crumbs?: Crumb[];
  header?: ComponentChildren;
  rail?: RailEntry[];
  asideLead?: PaneId;
  aside?: PaneId[];
  open?: PaneId;
}

function PaneSlot({ id, round, side, placement }: { id: PaneId; round: number; side: Side; placement: Placement }) {
  const Shown = panes[id];
  return <Shown round={round} side={side} placement={placement} />;
}

export function Console({ spec, round, side = spec.side, title, crumbs, header, rail = spec.rail, asideLead = spec.asideLead, aside = spec.aside, open }: ConsoleProps) {
  const place = usePlace();
  const onRail = (id: string) => rail.some((entry) => entry.pane === id);
  const besideOf = (id: PaneId) => rail.find((entry) => entry.pane === id)?.beside ?? [];
  const asideShown = asideLead ? [asideLead, ...aside] : aside;
  const fromHash = isPaneId(place.hash) && onRail(place.hash) ? place.hash : undefined;
  const first = rail[0]?.pane;
  const active = fromHash ?? (open && onRail(open) ? open : first);
  const [visited, setVisited] = useState<PaneId[]>([]);
  const mounted = active && !visited.includes(active) ? [...visited, active] : visited;
  if (mounted !== visited) setVisited(mounted);

  return (
    <AppPage console title={title} crumbs={crumbs ?? [{ label: title }]}>
      {header}
      <ConsoleLayout
        rail={rail.length > 0 && active
          ? <Rail items={rail.map((entry) => ({ id: entry.pane, label: t(entry.label), icon: entry.icon }))} value={active} onSelect={setHash} />
          : undefined}
        aside={asideShown.length > 0
          ? <Aside>{asideShown.map((id) => <PaneSlot key={id} id={id} round={round} side={side} placement={id === asideLead ? "aside-lead" : "aside"} />)}</Aside>
          : undefined}
      >
        {mounted.filter((id) => onRail(id)).map((id) => (
          <KeptPane key={id} shown={id === active}>
            {besideOf(id).length > 0
              ? <PaneSplit>{[id, ...besideOf(id)].map((shown) => <PaneSlot key={shown} id={shown} round={round} side={side} placement="main" />)}</PaneSplit>
              : <PaneSlot id={id} round={round} side={side} placement="main" />}
          </KeptPane>
        ))}
      </ConsoleLayout>
    </AppPage>
  );
}
