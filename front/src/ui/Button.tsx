import type { ComponentChildren } from "preact";
import { followLink } from "../router";
import { cx } from "./classes";
import { Icon, type IconName } from "./Icon";

export type ButtonTone = "primary" | "ghost" | "danger" | "dark" | "link";

export interface ButtonProps {
  tone?: ButtonTone;
  small?: boolean;
  block?: boolean;
  href?: string;
  external?: boolean;
  type?: "button" | "submit";
  disabled?: boolean;
  busy?: boolean;
  icon?: IconName;
  label?: string;
  onClick?: () => void;
  children?: ComponentChildren;
}

export function Button({ tone = "ghost", small, block, href, external, type = "button", disabled, busy, icon, label, onClick, children }: ButtonProps) {
  const classes = cx("btn", `btn-${tone}`, small && "btn-sm", block && "btn-block");
  const inside = (
    <>
      {icon && <Icon name={icon} size={16} />}
      {children}
    </>
  );
  if (href && !disabled) {
    return (
      <a class={classes} href={href} aria-label={label} target={external ? "_blank" : undefined} rel={external ? "noopener" : undefined}
        onClick={external ? undefined : (event) => followLink(event, href)}>
        {inside}
      </a>
    );
  }
  return (
    <button class={classes} type={type} disabled={disabled || busy} aria-busy={busy || undefined} aria-label={label} onClick={onClick}>
      {inside}
    </button>
  );
}

export interface LinkProps {
  href: string;
  className?: string;
  current?: boolean;
  children: ComponentChildren;
}

export function Link({ href, className, current, children }: LinkProps) {
  return (
    <a href={href} class={className} aria-current={current ? "page" : undefined} onClick={(event) => followLink(event, href)}>
      {children}
    </a>
  );
}
