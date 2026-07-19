import type { ReactNode } from "react";
import { cn } from "@/utils";

interface PanelProps {
  children: ReactNode;
  className?: string;
  title?: string;
  collapsible?: boolean;
}

export function Panel({ children, className, title }: PanelProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface",
        className,
      )}
      data-testid="panel"
    >
      {title && (
        <div className="border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold text-text">{title}</h3>
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}
