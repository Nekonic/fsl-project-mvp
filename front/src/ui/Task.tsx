import type { ComponentChildren } from "preact";
import { cx } from "./classes";

export interface TaskProps {
  no?: ComponentChildren;
  title: ComponentChildren;
  side?: ComponentChildren;
  state?: "open" | "done" | "error";
  foot?: ComponentChildren;
  children?: ComponentChildren;
}

export function Task({ no, title, side, state = "open", foot, children }: TaskProps) {
  return (
    <section class={cx("task", state === "done" && "task-done", state === "error" && "task-error")}>
      <div class="task-head">
        {no !== undefined && <span class="task-no">{no}</span>}
        <h2>{title}</h2>
        {side !== undefined && <div class="task-side">{side}</div>}
      </div>
      {children !== undefined && <div class="task-body">{children}</div>}
      {foot !== undefined && <div class="card-foot">{foot}</div>}
    </section>
  );
}
