import type { ComponentChildren } from "preact";
import { followLink } from "../router";
import { cx } from "./classes";
import { Icon, type IconName } from "./Icon";

export type TileTone = "blue" | "violet" | "green" | "pink" | "orange" | "cyan" | "red";

export interface TileProps {
  icon: IconName;
  tone?: TileTone;
  label?: ComponentChildren;
  title: ComponentChildren;
  text?: ComponentChildren;
  foot?: ComponentChildren;
  action?: ComponentChildren;
}

export function Tiles({ children }: { children: ComponentChildren }) {
  return <div class="tiles">{children}</div>;
}

export function Tile({ icon, tone = "blue", label, title, text, foot, action }: TileProps) {
  return (
    <div class="tile">
      <div class="tile-band" />
      <span class="tile-icon" data-tone={tone}><Icon name={icon} size={28} /></span>
      <div class="tile-body">
        {label && <span class="label">{label}</span>}
        <h4 class="tile-title">{title}</h4>
        {text && <p class="tile-text">{text}</p>}
        <div class="tile-foot">
          {foot}
          {action && <span class="tile-action">{action}</span>}
        </div>
      </div>
    </div>
  );
}

export interface TargetHeadProps {
  eyebrow?: ComponentChildren;
  title: ComponentChildren;
  text?: ComponentChildren;
  tag?: ComponentChildren;
}

export function TargetHead({ eyebrow, title, text, tag }: TargetHeadProps) {
  return (
    <div class="target-head">
      <div class="target-head-text">
        {eyebrow && <span class="label">{eyebrow}</span>}
        <h3>{title}</h3>
        {text && <p>{text}</p>}
      </div>
      {tag}
    </div>
  );
}

export interface ListRowProps {
  id: ComponentChildren;
  main?: ComponentChildren;
  side?: ComponentChildren;
  href?: string;
}

export function ListRow({ id, main, side, href }: ListRowProps) {
  const go = href ? (event: MouseEvent) => followLink(event, href) : undefined;
  return (
    <div class={cx("list-row", href && "list-row-link")}>
      {href ? <a class="list-row-id" href={href} onClick={go}>{id}</a> : <span class="list-row-id">{id}</span>}
      {href ? <a class="list-row-main" href={href} onClick={go}>{main}</a> : <div class="list-row-main">{main}</div>}
      {side && <div class="list-row-side">{side}</div>}
    </div>
  );
}
