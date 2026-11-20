import type { ComponentChildren } from "preact";
import { cx } from "./classes";

export type BadgeTone = "neutral" | "muted" | "info" | "ok" | "ok-strong" | "warn" | "danger" | "danger-strong" | "pass" | "fail";

export interface BadgeProps {
  tone?: BadgeTone;
  mono?: boolean;
  title?: string;
  children: ComponentChildren;
}

export function Badge({ tone = "neutral", mono, title, children }: BadgeProps) {
  return <span class={cx("badge", `badge-${tone}`, mono && "badge-mono")} title={title}>{children}</span>;
}

export function Badges({ children }: { children: ComponentChildren }) {
  return <span class="badges">{children}</span>;
}

export type DotTone = "ok" | "warn" | "danger" | "off";

export function Dot({ tone = "off" }: { tone?: DotTone }) {
  return <span class={cx("dot", tone !== "off" && `dot-${tone}`)} aria-hidden="true" />;
}
