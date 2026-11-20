import type { ComponentChildren, JSX } from "preact";
import { cx } from "./classes";

export interface FieldProps {
  label?: ComponentChildren;
  error?: string;
  hint?: ComponentChildren;
  wide?: boolean;
  children: ComponentChildren;
}

export function Field({ label, error, hint, wide, children }: FieldProps) {
  return (
    <label class={cx("field", wide && "span-2")}>
      {label && <span class="field-label">{label}</span>}
      {children}
      {hint && !error && <span class="field-hint">{hint}</span>}
      {error && <span class="field-error">{error}</span>}
    </label>
  );
}

type InputAttributes = Omit<JSX.InputHTMLAttributes<HTMLInputElement>, "onInput" | "value" | "class" | "className">;

export interface InputProps extends InputAttributes {
  value: string | number;
  onValue: (value: string) => void;
  mono?: boolean;
  bad?: boolean;
}

export function Input({ value, onValue, mono, bad, ...rest }: InputProps) {
  return (
    <input {...rest} class={cx("input", mono && "input-mono", bad && "is-bad")} value={value}
      onInput={(event) => onValue((event.currentTarget as HTMLInputElement).value)} />
  );
}

export interface TextAreaProps {
  value: string;
  onValue: (value: string) => void;
  rows?: number;
  mono?: boolean;
  bad?: boolean;
  placeholder?: string;
  label?: string;
  disabled?: boolean;
}

export function TextArea({ value, onValue, rows = 4, mono, bad, placeholder, label, disabled }: TextAreaProps) {
  return (
    <textarea class={cx("input", mono && "input-mono", bad && "is-bad")} rows={rows} value={value} placeholder={placeholder}
      aria-label={label} disabled={disabled} spellcheck={false}
      onInput={(event) => onValue((event.currentTarget as HTMLTextAreaElement).value)} />
  );
}

export interface Option {
  value: string;
  label: ComponentChildren;
}

export interface SelectProps {
  value: string;
  options: Option[];
  onValue: (value: string) => void;
  mono?: boolean;
  bad?: boolean;
  disabled?: boolean;
  label?: string;
}

export function Select({ value, options, onValue, mono, bad, disabled, label }: SelectProps) {
  return (
    <select class={cx("input", mono && "input-mono", bad && "is-bad")} value={value} disabled={disabled} aria-label={label}
      onChange={(event) => onValue((event.currentTarget as HTMLSelectElement).value)}>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  );
}

export interface CheckboxProps {
  checked: boolean;
  onChecked: (checked: boolean) => void;
  label: ComponentChildren;
  disabled?: boolean;
}

export function Checkbox({ checked, onChecked, label, disabled }: CheckboxProps) {
  return (
    <label class="check">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChecked((event.currentTarget as HTMLInputElement).checked)} />
      {label}
    </label>
  );
}

export interface SwitchProps {
  checked: boolean;
  onChecked: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

export function Switch({ checked, onChecked, label, disabled }: SwitchProps) {
  return <button type="button" class="switch" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChecked(!checked)} />;
}

export interface ChoicesProps {
  name: string;
  value: string;
  options: Option[];
  onValue: (value: string) => void;
  inline?: boolean;
}

export function Choices({ name, value, options, onValue, inline }: ChoicesProps) {
  return (
    <div class={inline ? "radios" : "choices"}>
      {options.map((option) => (
        <label key={option.value} class={inline ? undefined : "choice"}>
          <input type="radio" name={name} value={option.value} checked={option.value === value} onChange={() => onValue(option.value)} />
          {option.label}
        </label>
      ))}
    </div>
  );
}

export interface FormProps {
  onSubmit: () => void;
  children: ComponentChildren;
}

export function Form({ onSubmit, children }: FormProps) {
  return (
    <form class="form" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
      {children}
    </form>
  );
}

export function FormGrid({ four, children }: { four?: boolean; children: ComponentChildren }) {
  return <div class={four ? "form-grid-4" : "form-grid"}>{children}</div>;
}

export function FormActions({ children }: { children: ComponentChildren }) {
  return <div class="form-actions">{children}</div>;
}

export function Filters({ children }: { children: ComponentChildren }) {
  return <div class="filters">{children}</div>;
}
