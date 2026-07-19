import type { ReactNode } from "react";
import { cn } from "@/utils";

interface TimelineItem {
  timestamp: number;
  title: string;
  description?: string;
  icon?: ReactNode;
  status?: "default" | "success" | "warning" | "error";
}

interface TimelineProps {
  items: TimelineItem[];
  className?: string;
}

const statusColor = {
  default: "bg-text-subtle",
  success: "bg-status-success",
  warning: "bg-status-warning",
  error: "bg-status-error",
};

export function Timeline({ items, className }: TimelineProps) {
  if (items.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-text-muted" data-testid="timeline-empty">
        Nenhum evento na timeline.
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col", className)} data-testid="timeline">
      {items.map((item, i) => (
        <div key={i} className="flex gap-3 pb-4 last:pb-0">
          <div className="flex flex-col items-center">
            <span
              className={cn(
                "mt-1 h-3 w-3 rounded-full",
                statusColor[item.status ?? "default"],
              )}
              aria-hidden="true"
            />
            {i < items.length - 1 && <span className="w-px flex-1 bg-border" />}
          </div>
          <div className="flex flex-1 flex-col gap-0.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-text">{item.title}</span>
              {item.timestamp > 0 && (
                <span className="text-xs text-text-subtle">
                  {new Date(item.timestamp * 1000).toLocaleTimeString("pt-BR")}
                </span>
              )}
            </div>
            {item.description && (
              <span className="text-xs text-text-muted">{item.description}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
