/**
 * SeverityBadge — badge de severidade de um evento.
 *
 * Mostra ícone + texto + tooltip. Nunca depende apenas de cor.
 */

import { Info, AlertTriangle, AlertCircle, XCircle, Circle } from "lucide-react";
import type { EventSeverity } from "./event-categories";
import { cn } from "@/utils";

interface SeverityBadgeProps {
  severity: EventSeverity;
  className?: string;
}

const SEVERITY_CONFIG: Record<EventSeverity, {
  label: string;
  colorClass: string;
  icon: typeof Info;
}> = {
  info: { label: "Info", colorClass: "text-status-info", icon: Info },
  low: { label: "Baixa", colorClass: "text-status-healthy", icon: Circle },
  medium: { label: "Média", colorClass: "text-status-warning", icon: AlertTriangle },
  high: { label: "Alta", colorClass: "text-status-error", icon: AlertCircle },
  critical: { label: "Crítica", colorClass: "text-status-error", icon: XCircle },
};

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  const config = SEVERITY_CONFIG[severity];
  const Icon = config.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium",
        config.colorClass,
        className,
      )}
      title={`Severidade: ${config.label}`}
      data-testid="severity-badge"
      data-severity={severity}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {config.label}
    </span>
  );
}
