import { cn } from "@/utils";
import {
  STATUS_CONFIG,
  type VisualStatus,
} from "@/shared/status";

interface StatusBadgeProps {
  status: VisualStatus;
  label?: string;
  showDot?: boolean;
  className?: string;
}

export function StatusBadge({
  status,
  label,
  showDot = true,
  className,
}: StatusBadgeProps) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        config.colorClass,
        config.bgClass,
        config.borderClass,
        className,
      )}
      data-testid="status-badge"
      data-status={status}
    >
      {showDot && (
        <span
          className={cn("h-1.5 w-1.5 rounded-full", config.dotClass)}
          aria-hidden="true"
        />
      )}
      {label ?? config.label}
    </span>
  );
}
