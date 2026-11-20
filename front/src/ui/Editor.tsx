import { cx } from "./classes";

export interface CodeEditorProps {
  value: string;
  onValue: (value: string) => void;
  label: string;
  badLines?: Set<number>;
  bad?: boolean;
  minLines?: number;
}

export function CodeEditor({ value, onValue, label, badLines, bad, minLines = 1 }: CodeEditorProps) {
  const lines = Math.max(minLines, value.split("\n").length);
  return (
    <div class={cx("editor", minLines > 1 && "editor-tall", bad && "is-bad")}>
      <div class="editor-gutter" aria-hidden="true">
        {Array.from({ length: lines }, (_, index) => <span key={index} class={badLines?.has(index + 1) ? "is-bad" : undefined}>{index + 1}</span>)}
      </div>
      <textarea class="editor-text" rows={lines} wrap="off" spellcheck={false} aria-label={label} value={value}
        onInput={(event) => onValue((event.currentTarget as HTMLTextAreaElement).value)} />
    </div>
  );
}
