import type { ComponentChildren } from "preact";
import { useRef, useState } from "preact/hooks";
import { Badge, type BadgeTone } from "./Badge";
import { Button, Link } from "./Button";
import type { Option } from "./Field";
import { cx } from "./classes";

export function Split({ list, children }: { list: ComponentChildren; children: ComponentChildren }) {
  return (
    <div class="split">
      {list}
      <div class="split-main">{children}</div>
    </div>
  );
}

export function EditorCard({ children }: { children: ComponentChildren }) {
  return <section class="card editor-card">{children}</section>;
}

export interface EditorHeadProps {
  eyebrow?: ComponentChildren;
  title: ComponentChildren;
  actions?: ComponentChildren;
}

export function EditorHead({ eyebrow, title, actions }: EditorHeadProps) {
  return (
    <div class="editor-head">
      <div class="editor-head-text">
        {eyebrow && <p class="editor-eyebrow">{eyebrow}</p>}
        <h2 class="editor-heading">{title}</h2>
      </div>
      {actions && <div class="editor-actions">{actions}</div>}
    </div>
  );
}

export interface EditorStripProps {
  tone?: "plain" | "danger" | "ok";
  title?: ComponentChildren;
  action?: ComponentChildren;
  children?: ComponentChildren;
}

export function EditorStrip({ tone = "plain", title, action, children }: EditorStripProps) {
  if (title && tone === "plain") {
    return (
      <div class="editor-strip editor-strip-block">
        <p class="editor-strip-title">{title}</p>
        {children}
      </div>
    );
  }
  return (
    <div class={cx("editor-strip", tone !== "plain" && `editor-strip-${tone}`)} role={tone === "danger" ? "alert" : undefined}>
      {title && <span>{title}</span>}
      {children}
      {action && <span class="editor-strip-action">{action}</span>}
    </div>
  );
}

export function EditorSection({ ruled, children }: { ruled?: boolean; children: ComponentChildren }) {
  return <div class={cx("editor-section", ruled && "is-ruled")}>{children}</div>;
}

export function EditorBand({ title, children }: { title: ComponentChildren; children?: ComponentChildren }) {
  return (
    <div class="editor-band">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function FieldNote({ children }: { children?: ComponentChildren }) {
  if (!children) return null;
  return <p class="field-error">{children}</p>;
}

export function EditorGroup({ label, wide, children }: { label: ComponentChildren; wide?: boolean; children: ComponentChildren }) {
  return (
    <div class={cx("editor-group", wide && "span-2")}>
      <span class="label">{label}</span>
      {children}
    </div>
  );
}

export interface ChipsProps {
  value: string;
  options: Option[];
  onValue: (value: string) => void;
  label?: string;
}

export function Chips({ value, options, onValue, label }: ChipsProps) {
  return (
    <div class="chips" role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option.value} type="button" class="btn btn-sm btn-ghost chip" aria-pressed={option.value === value} onClick={() => onValue(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

export interface PickItem {
  id: number | string;
  no?: ComponentChildren;
  title: ComponentChildren;
  sub?: ComponentChildren[];
  badge?: { tone: BadgeTone; text: ComponentChildren };
  href: string;
  current: boolean;
}

export interface PickGroup {
  title: ComponentChildren;
  items: PickItem[];
}

export function PickList({ title, count, groups, empty }: { title: ComponentChildren; count: ComponentChildren; groups: PickGroup[]; empty?: ComponentChildren }) {
  return (
    <aside class="card editor-card">
      <div class="card-head">
        <h2>{title}</h2>
        <Badge>{count}</Badge>
      </div>
      {groups.length === 0 && empty && <p class="empty card-pad-sm">{empty}</p>}
      {groups.map((group, index) => (
        <div key={index}>
          <div class="list-group">{group.title}</div>
          {group.items.map((item) => (
            <Link key={item.id} href={item.href} className="pick-row" current={item.current}>
              {item.no !== undefined && <span class="pick-no">{item.no}</span>}
              <span class="pick-main">
                <span class="pick-title">{item.title}</span>
                {item.sub?.map((line, place) => <span key={place} class="pick-sub">{line}</span>)}
              </span>
              {item.badge && <Badge tone={item.badge.tone}>{item.badge.text}</Badge>}
            </Link>
          ))}
        </div>
      ))}
    </aside>
  );
}

export interface LineItem {
  text: string;
  tag?: ComponentChildren;
  bad?: boolean;
  note?: ComponentChildren;
}

export interface LineListProps {
  lines: LineItem[];
  removeLabel: ComponentChildren;
  onRemove: (index: number) => void;
  addLabel: ComponentChildren;
  placeholder: string;
  onAdd: (text: string) => void | Promise<string | undefined>;
}

export function LineList({ lines, removeLabel, onRemove, addLabel, placeholder, onAdd }: LineListProps) {
  const [typed, setTyped] = useState("");
  const [refusal, setRefusal] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const text = typed.trim();
  const add = async () => {
    if (!text || busy) return;
    setBusy(true);
    try {
      const refused = await onAdd(text);
      setRefusal(refused || undefined);
      if (!refused) setTyped("");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      {lines.map((line, index) => [
        <div key={`l${index}`} class={cx("case-line", line.bad && "is-bad")}>
          <span class="ellipsis">{line.text}</span>
          {line.tag}
          <button type="button" class="case-line-end" onClick={() => onRemove(index)}>{removeLabel}</button>
        </div>,
        line.note && <p key={`n${index}`} class="field-error">{line.note}</p>,
      ])}
      <div class="line-add">
        <input class="input input-mono" value={typed} placeholder={placeholder} aria-label={placeholder}
          onInput={(event) => { setTyped((event.currentTarget as HTMLInputElement).value); setRefusal(undefined); }}
          onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void add(); } }} />
        <Button small disabled={!text} busy={busy} onClick={() => void add()}>{addLabel}</Button>
      </div>
      {refusal && <p class="field-error">{refusal}</p>}
    </div>
  );
}

export function WithUnit({ unit, children }: { unit: ComponentChildren; children: ComponentChildren }) {
  return <span class="with-unit">{children}<span>{unit}</span></span>;
}

export interface PublishRowProps {
  ruled?: boolean;
  children: ComponentChildren;
  end?: ComponentChildren;
  note?: ComponentChildren;
}

export function PublishRow({ ruled, children, end, note }: PublishRowProps) {
  return (
    <div class={cx("publish-row", ruled && "is-ruled")}>
      {children}
      {end && <span class="publish-end">{end}</span>}
      {note && <p class="publish-note field-error">{note}</p>}
    </div>
  );
}

export interface FilePickProps {
  label: ComponentChildren;
  busy?: boolean;
  accept?: string;
  onFile: (file: File) => void;
}

export function FilePick({ label, busy, accept = "application/json,.json", onFile }: FilePickProps) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={input} type="file" accept={accept} hidden
        onChange={(event) => {
          const picked = (event.currentTarget as HTMLInputElement).files?.[0];
          if (picked) onFile(picked);
          (event.currentTarget as HTMLInputElement).value = "";
        }} />
      <Button busy={busy} onClick={() => input.current?.click()}>{label}</Button>
    </>
  );
}
