import type { ComponentChildren } from "preact";
import { cx } from "./classes";
import { Prose } from "./Text";

export type StepState = "done" | "now" | "locked";

export function StepCardFrame({ done, count, children }: { done?: boolean; count: ComponentChildren; children: ComponentChildren }) {
  return (
    <section class={cx("step-card", done && "is-done")}>
      <span class="step-count">{count}</span>
      {children}
    </section>
  );
}

export function HintBox({ title, children }: { title: ComponentChildren; children: ComponentChildren }) {
  return (
    <div class="hint">
      <b>{title}</b>
      <Prose>{children}</Prose>
    </div>
  );
}

export function StepRows({ children }: { children: ComponentChildren }) {
  return <ol class="steps">{children}</ol>;
}

export function StepRow({ state, mark, body, label }: { state: StepState; mark: ComponentChildren; body: ComponentChildren; label?: ComponentChildren }) {
  return (
    <li class={cx("step-row", `is-${state}`)}>
      <span class="step-mark">{mark}</span>
      <span>{body}</span>
      {label && <span class="step-state">{label}</span>}
    </li>
  );
}
