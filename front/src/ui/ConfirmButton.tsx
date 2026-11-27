import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import { Button, type ButtonTone } from "./Button";

export const CONFIRM_ARMED_MS = 5_000;

export interface ConfirmButtonProps {
  tone?: ButtonTone;
  armedTone?: ButtonTone;
  small?: boolean;
  busy?: boolean;
  disabled?: boolean;
  confirm: ComponentChildren;
  onConfirm: () => void;
  children: ComponentChildren;
}

export function ConfirmButton({ tone = "ghost", armedTone = "danger", small, busy, disabled, confirm, onConfirm, children }: ConfirmButtonProps) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return undefined;
    const timer = setTimeout(() => setArmed(false), CONFIRM_ARMED_MS);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setArmed(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, [armed]);
  const press = () => {
    if (!armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    onConfirm();
  };
  return (
    <Button tone={armed ? armedTone : tone} small={small} busy={busy} disabled={disabled} onClick={press}>
      {armed ? confirm : children}
    </Button>
  );
}
