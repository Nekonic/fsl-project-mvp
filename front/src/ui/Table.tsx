import type { ComponentChildren } from "preact";
import { cx } from "./classes";

export type CellKind = "text" | "num" | "end" | "mono" | "key" | "strong" | "wrap" | "nowrap" | "cut" | "break";

export interface Column<Row> {
  key: string;
  label: ComponentChildren;
  kind?: CellKind;
  cell: (row: Row, index: number) => ComponentChildren;
  title?: (row: Row) => string | undefined;
}

export interface TableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row, index: number) => string | number;
  variant?: "plain" | "grid" | "compact";
  empty?: ComponentChildren;
  foot?: ComponentChildren;
  onRow?: (row: Row) => void;
  selected?: (row: Row) => boolean;
  muted?: (row: Row) => boolean;
  scroll?: boolean;
}

const VARIANT = { plain: "table", grid: "table-grid", compact: "table-compact" } as const;

function cellClass(kind: CellKind | undefined): string | undefined {
  return kind && kind !== "text" ? `cell-${kind}` : undefined;
}

export function Table<Row>({ columns, rows, rowKey, variant = "plain", empty, foot, onRow, selected, muted, scroll = true }: TableProps<Row>) {
  if (!rows.length && empty !== undefined) return <p class="empty">{empty}</p>;
  const table = (
    <table class={VARIANT[variant]}>
      <thead>
        <tr>{columns.map((column) => <th key={column.key} class={column.kind === "num" || column.kind === "end" ? "cell-end" : undefined}>{column.label}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={rowKey(row, index)} data-link={onRow ? "" : undefined} aria-selected={selected ? selected(row) : undefined}
            class={muted?.(row) ? "is-muted" : undefined} onClick={onRow ? () => onRow(row) : undefined}>
            {columns.map((column) => <td key={column.key} class={cellClass(column.kind)} title={column.title?.(row)}>{column.cell(row, index)}</td>)}
          </tr>
        ))}
      </tbody>
      {foot && <tfoot>{foot}</tfoot>}
    </table>
  );
  return scroll ? <div class={cx("table-scroll")}>{table}</div> : table;
}

export function FootRow({ label, value, span }: { label: ComponentChildren; value: ComponentChildren; span: number }) {
  return (
    <tr>
      <td colSpan={span}>{label}</td>
      <td class="cell-end">{value}</td>
    </tr>
  );
}
