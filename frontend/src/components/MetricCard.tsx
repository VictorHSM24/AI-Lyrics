import type { ReactNode } from "react";
import { cn } from "@/utils";
import { StatusBadge } from "@/components/StatusBadge";
import type { VisualStatus } from "@/shared/status";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  unit?: string;
  status?: VisualStatus;
  description?: string;
  icon?: ReactNode;
  className?: string;
}

export function MetricCard({
  label,
  value,
  unit,
  status,
  description,
  icon,
  className,
}: MetricCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface-raised p-4",
        className,
      )}
      data-testid="metric-card"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-text-muted">{label}</span>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-text">{value}</span>
            {unit && <span className="text-sm text-text-muted">{unit}</span>}
          </div>
          {description && (
            <span className="text-xs text-text-subtle">{description}</span>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          {icon && <span className="text-text-muted">{icon}</span>}
          {status && <StatusBadge status={status} />}
        </div>
      </div>
    </div>
  );
}
