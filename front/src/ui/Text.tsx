import type { ComponentChildren } from "preact";
import { cx } from "./classes";

export type TextTone = "heading" | "muted" | "faint" | "ok" | "warn" | "danger" | "info" | "attack" | "defence";

export interface TextProps {
  tone?: TextTone;
  mono?: boolean;
  strong?: boolean;
  small?: boolean;
  tiny?: boolean;
  cut?: boolean;
  title?: string;
  children: ComponentChildren;
}

export function Text({ tone, mono, strong, small, tiny, cut, title, children }: TextProps) {
  return (
    <span class={cx(tone && `tone-${tone}`, mono && "mono num", strong && "strong", small && "small", tiny && "tiny", cut && "ellipsis") || undefined} title={title}>
      {children}
    </span>
  );
}

export function Prose({ children }: { children: ComponentChildren }) {
  return <p class="prose">{children}</p>;
}

export function Label({ children }: { children: ComponentChildren }) {
  return <span class="label">{children}</span>;
}

export function Subhead({ children }: { children: ComponentChildren }) {
  return <h3 class="subhead">{children}</h3>;
}

export function Code({ wrap, children }: { wrap?: boolean; children: ComponentChildren }) {
  return <pre class={cx("code", wrap && "code-wrap")}>{children}</pre>;
}

export interface ProgressProps {
  value: number;
  max: number;
  label?: string;
}

export function Progress({ value, max, label }: ProgressProps) {
  const share = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div class="progress" role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <i style={{ width: `${share}%` }} />
    </div>
  );
}

export interface StatProps {
  label: ComponentChildren;
  value: ComponentChildren;
}

export function Stat({ label, value }: StatProps) {
  return (
    <span class="stat">
      <span class="stat-label">{label}</span>
      <b class="stat-value">{value}</b>
    </span>
  );
}

export function Stats({ children }: { children: ComponentChildren }) {
  return <div class="stats">{children}</div>;
}

export interface KeyValueProps {
  items: Array<[ComponentChildren, ComponentChildren]>;
  facts?: boolean;
}

export function KeyValue({ items, facts }: KeyValueProps) {
  if (facts) {
    return <dl class="facts">{items.map(([name, value], index) => <div key={index}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>;
  }
  return <dl class="kv">{items.map(([name, value], index) => [<dt key={`k${index}`}>{name}</dt>, <dd key={`v${index}`}>{value}</dd>])}</dl>;
}

export function Empty({ children }: { children: ComponentChildren }) {
  return <p class="empty">{children}</p>;
}

export function Loading({ children }: { children: ComponentChildren }) {
  return <p class="loading" aria-busy="true">{children}</p>;
}

export function Divided({ children }: { children: ComponentChildren }) {
  return <div class="divided">{children}</div>;
}
