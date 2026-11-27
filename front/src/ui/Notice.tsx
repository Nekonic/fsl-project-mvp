import type { ComponentChildren } from "preact";
import { errorLines, type ErrorShape } from "../strings";
import { cx } from "./classes";

export type NoticeTone = "plain" | "danger" | "warn" | "ok" | "info";

export interface NoticeProps {
  tone?: NoticeTone;
  title?: ComponentChildren;
  detail?: ComponentChildren;
  action?: ComponentChildren;
  inline?: boolean;
  children?: ComponentChildren;
}

export function Notice({ tone = "plain", title, detail, action, inline, children }: NoticeProps) {
  return (
    <div class={cx("notice", tone !== "plain" && `notice-${tone}`, inline && "notice-inline")} role={tone === "danger" ? "alert" : undefined}>
      {title && <b class="notice-title">{title}</b>}
      {children && <span>{children}</span>}
      {action && <span class="notice-action">{action}</span>}
      {detail && <span class="notice-detail">{detail}</span>}
    </div>
  );
}

export interface ErrorNoticeProps {
  error: ErrorShape | null | undefined;
  inline?: boolean;
  action?: ComponentChildren;
}

export function ErrorNotice({ error, inline, action }: ErrorNoticeProps) {
  const lines = errorLines(error);
  if (!lines.length) return null;
  return (
    <Notice tone="danger" inline={inline} action={action}>
      {lines.length === 1 ? lines[0] : <ul>{lines.map((line, index) => <li key={index}>{line}</li>)}</ul>}
    </Notice>
  );
}

export interface ErrorListProps {
  items: Array<{ path: string; text: string }>;
}

export function ErrorList({ items }: ErrorListProps) {
  if (!items.length) return null;
  return (
    <ul class="error-list">
      {items.map((item, index) => <li key={index}>{item.path && <><span class="error-path">{item.path}</span>{" "}</>}{item.text}</li>)}
    </ul>
  );
}

export interface BannerProps {
  tone?: "plain" | "danger";
  title: ComponentChildren;
  detail?: ComponentChildren;
  action?: ComponentChildren;
}

export function Banner({ tone = "plain", title, detail, action }: BannerProps) {
  return (
    <div class={cx("banner", tone === "danger" && "banner-danger")}>
      <span class="banner-title">{title}</span>
      {detail && <span class="tone-muted">{detail}</span>}
      {action && <span class="banner-action">{action}</span>}
    </div>
  );
}
