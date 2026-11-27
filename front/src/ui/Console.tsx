import type { ComponentChildren } from "preact";
import { cx } from "./classes";
import { Icon, type IconName } from "./Icon";

export type SideMark = "attack" | "defence";

export interface RoundFact {
  label: ComponentChildren;
  value: ComponentChildren;
  mono?: boolean;
}

export interface RoundBarProps {
  side: SideMark;
  sideLabel: ComponentChildren;
  what?: ComponentChildren;
  badges?: ComponentChildren;
  facts?: RoundFact[];
  actions?: ComponentChildren;
}

export function RoundBar({ side, sideLabel, what, badges, facts = [], actions }: RoundBarProps) {
  return (
    <div class="roundbar">
      <div class="roundbar-title">
        <span class="roundbar-side" data-side={side}>{sideLabel}</span>
        {what && <span class="roundbar-what">{what}</span>}
      </div>
      <div class="roundbar-meta">
        {badges}
        {facts.map((fact, index) => (
          <span class="roundbar-fact" key={index}><span>{fact.label}</span><b class={fact.mono ? "mono" : undefined}>{fact.value}</b></span>
        ))}
      </div>
      {actions && <div class="roundbar-actions">{actions}</div>}
    </div>
  );
}

export interface RailItem {
  id: string;
  label: ComponentChildren;
  icon: IconName;
}

export interface RailProps {
  items: RailItem[];
  value: string;
  onSelect: (id: string) => void;
}

export function Rail({ items, value, onSelect }: RailProps) {
  return (
    <nav class="rail" role="tablist">
      {items.map((item) => (
        <button key={item.id} type="button" role="tab" class="rail-btn" aria-selected={item.id === value} onClick={() => onSelect(item.id)}>
          <Icon name={item.icon} />
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}

export interface ConsoleLayoutProps {
  rail?: ComponentChildren;
  aside?: ComponentChildren;
  children: ComponentChildren;
}

export function ConsoleLayout({ rail, aside, children }: ConsoleLayoutProps) {
  return (
    <div class="console">
      {rail}
      <div class="console-main">{children}</div>
      {aside}
    </div>
  );
}

export function KeptPane({ shown, children }: { shown: boolean; children: ComponentChildren }) {
  return <div class={shown ? "pane" : "pane pane-kept"} aria-hidden={shown ? undefined : true} inert={shown ? undefined : true}>{children}</div>;
}

export function PaneSplit({ children }: { children: ComponentChildren }) {
  return <div class="pane-split">{children}</div>;
}

export interface PaneProps {
  title?: ComponentChildren;
  meta?: ComponentChildren;
  actions?: ComponentChildren;
  dark?: boolean;
  scroll?: boolean;
  children: ComponentChildren;
}

export function Pane({ title, meta, actions, dark, scroll = true, children }: PaneProps) {
  return (
    <section class={cx("pane", dark && "pane-dark")}>
      {(title || meta || actions) && <PaneHeader title={title} meta={meta} actions={actions} />}
      {scroll ? <div class="pane-scroll">{children}</div> : children}
    </section>
  );
}

export interface PaneHeaderProps {
  title?: ComponentChildren;
  meta?: ComponentChildren;
  actions?: ComponentChildren;
}

export function PaneHeader({ title, meta, actions }: PaneHeaderProps) {
  return (
    <div class="pane-bar">
      {title && <b class="pane-title">{title}</b>}
      {meta && <span class="pane-meta">{meta}</span>}
      {actions && <div class="pane-actions">{actions}</div>}
    </div>
  );
}

export interface PaneSectionProps {
  title?: ComponentChildren;
  meta?: ComponentChildren;
  actions?: ComponentChildren;
  ruled?: boolean;
  children?: ComponentChildren;
}

export function PaneSection({ title, meta, actions, ruled, children }: PaneSectionProps) {
  return (
    <section class={cx("pane-section", ruled && "is-ruled")}>
      {(title || actions) && (
        <div class="pane-section-head">
          {title && <h2>{title}</h2>}
          {meta && <span class="tone-muted">{meta}</span>}
          {actions && <div class="pane-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Aside({ head, children }: { head?: ComponentChildren; children?: ComponentChildren }) {
  return (
    <aside class="aside">
      {head}
      <div class="aside-body">{children}</div>
    </aside>
  );
}

export interface AsideHeadProps {
  title: ComponentChildren;
  value?: ComponentChildren;
  sub?: [ComponentChildren, ComponentChildren];
  progress?: ComponentChildren;
  actions?: ComponentChildren;
}

export function AsideHead({ title, value, sub, progress, actions }: AsideHeadProps) {
  return (
    <header class="aside-head">
      <div class="aside-head-row">
        <h2 class="aside-head-title">{title}</h2>
        {value !== undefined && <span class="aside-head-value">{value}</span>}
        {actions}
      </div>
      {sub && <div class="aside-head-sub"><span>{sub[0]}</span><span>{sub[1]}</span></div>}
      {progress}
    </header>
  );
}

export interface AsideCardProps {
  title?: ComponentChildren;
  meta?: ComponentChildren;
  lost?: boolean;
  children?: ComponentChildren;
}

export function AsideCard({ title, meta, lost, children }: AsideCardProps) {
  return (
    <div class={cx("aside-card", lost && "is-lost")}>
      {(title || meta !== undefined) && (
        <div class="aside-card-head">
          {title && <b>{title}</b>}
          {meta !== undefined && <span>{meta}</span>}
        </div>
      )}
      {children}
    </div>
  );
}

export interface AsideFoldProps {
  title: ComponentChildren;
  meta?: ComponentChildren;
  children?: ComponentChildren;
}

export function AsideFold({ title, meta, children }: AsideFoldProps) {
  return (
    <details class="aside-card aside-fold">
      <summary class="aside-card-head">
        <b>{title}</b>
        {meta !== undefined && <span>{meta}</span>}
      </summary>
      {children}
    </details>
  );
}

export function RowLine({ children }: { children: ComponentChildren }) {
  return <div class="row-line">{children}</div>;
}

export interface FrameProps {
  src: string;
  title: string;
  dark?: boolean;
  sandbox?: string;
}

export function Frame({ src, title, dark, sandbox }: FrameProps) {
  return <iframe class={dark ? "term-frame" : "frame"} src={src} title={title} sandbox={sandbox} />;
}

export interface FrameEmptyProps {
  title?: ComponentChildren;
  dark?: boolean;
  children?: ComponentChildren;
}

export function FrameEmpty({ title, dark, children }: FrameEmptyProps) {
  if (dark) return <div class="term-empty">{children}</div>;
  return (
    <div class="frame-empty">
      {title && <b>{title}</b>}
      {children && <span>{children}</span>}
    </div>
  );
}
