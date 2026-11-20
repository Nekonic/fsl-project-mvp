import type { ComponentChildren } from "preact";
import { cx } from "./classes";

export interface CardProps {
  pad?: "none" | "sm" | "md";
  list?: boolean;
  scroll?: boolean;
  children: ComponentChildren;
}

export function Card({ pad = "none", list, scroll, children }: CardProps) {
  return (
    <div class={cx("card", pad === "md" && "card-pad", pad === "sm" && "card-pad-sm", list && "card-list", scroll && "table-scroll")}>
      {children}
    </div>
  );
}

export interface CardHeadProps {
  title: ComponentChildren;
  meta?: ComponentChildren;
  actions?: ComponentChildren;
}

export function CardHead({ title, meta, actions }: CardHeadProps) {
  return (
    <div class="card-head">
      <h2>{title}</h2>
      {meta !== undefined && <span class="tone-muted small">{meta}</span>}
      {actions && <div class="card-actions">{actions}</div>}
    </div>
  );
}

export function CardFoot({ children }: { children: ComponentChildren }) {
  return <div class="card-foot">{children}</div>;
}

export function CardTitle({ children }: { children: ComponentChildren }) {
  return <h1 class="card-title">{children}</h1>;
}

export interface SectionProps {
  title?: ComponentChildren;
  sub?: ComponentChildren;
  actions?: ComponentChildren;
  large?: boolean;
  children?: ComponentChildren;
}

export function Section({ title, sub, actions, large, children }: SectionProps) {
  return (
    <section>
      {(title || actions) && (
        <div class="section-head">
          {title && <h2 class={large ? "section-title-lg" : "section-title"}>{title}</h2>}
          {sub !== undefined && <span class="section-sub">{sub}</span>}
          {actions && <div class="section-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Group({ children }: { children: ComponentChildren }) {
  return <section class="group">{children}</section>;
}

export function GroupHead({ title, sub }: { title: ComponentChildren; sub?: ComponentChildren }) {
  return (
    <div class="group-head">
      <h4>{title}</h4>
      {sub !== undefined && <span class="section-sub">{sub}</span>}
    </div>
  );
}

export interface StackProps {
  gap?: "sm" | "md" | "lg";
  children: ComponentChildren;
}

export function Stack({ gap = "md", children }: StackProps) {
  return <div class={gap === "sm" ? "stack-sm" : gap === "lg" ? "stack-lg" : "stack"}>{children}</div>;
}

export function Row({ wide, children }: { wide?: boolean; children: ComponentChildren }) {
  return <div class={wide ? "row-wide" : "row"}>{children}</div>;
}

export function Push({ children }: { children: ComponentChildren }) {
  return <span class="push">{children}</span>;
}

export interface ColumnsProps {
  shape?: "main-side" | "two";
  children: ComponentChildren;
}

export function Columns({ shape = "main-side", children }: ColumnsProps) {
  return <div class={cx("columns", `columns-${shape}`)}>{children}</div>;
}
