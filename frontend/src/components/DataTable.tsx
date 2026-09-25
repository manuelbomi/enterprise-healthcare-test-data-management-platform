import type { ReactNode } from "react";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Right-aligns numeric columns. */
  align?: "left" | "right";
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowKey: (row: T) => string;
  caption: string;
  emptyMessage?: string;
}

/** A plain, accessible `<table>` -- semantic HTML first (per
 * `docs/adr/0008-frontend-stack.md`), a real `<caption>` (visually
 * available, screen-reader-first) instead of a floating heading glued
 * to the table only by proximity. Used by every list-shaped page in
 * this console (Data Catalog, Datasets, Subsetting Jobs, ...) instead of
 * each hand-rolling its own table markup. */
export function DataTable<T>({ columns, rows, getRowKey, caption, emptyMessage = "No rows to display." }: DataTableProps<T>) {
  if (rows.length === 0) {
    return <p className="data-table__empty">{emptyMessage}</p>;
  }
  return (
    <div className="data-table-wrapper">
      <table className="data-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={column.align === "right" ? "align-right" : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={getRowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} className={column.align === "right" ? "align-right" : undefined}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
