import type { ReactNode } from "react";
import { cn } from "@/utils";

interface Column<T> {
  key: keyof T | string;
  header: string;
  render?: (row: T) => ReactNode;
  className?: string;
}

interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  emptyMessage?: string;
  className?: string;
}

export function Table<T extends Record<string, unknown>>({
  columns,
  data,
  emptyMessage = "Nenhum dado disponível.",
  className,
}: TableProps<T>) {
  if (data.length === 0) {
    return (
      <div
        className="py-8 text-center text-sm text-text-muted"
        data-testid="table-empty"
      >
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto", className)} data-testid="table">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            {columns.map((col) => (
              <th
                key={String(col.key)}
                className={cn("px-3 py-2 font-medium text-text-muted", col.className)}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr
              key={i}
              className="border-b border-border/50 hover:bg-surface-hover"
            >
              {columns.map((col) => (
                <td key={String(col.key)} className={cn("px-3 py-2 text-text", col.className)}>
                  {col.render
                    ? col.render(row)
                    : String(row[col.key as keyof T] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
