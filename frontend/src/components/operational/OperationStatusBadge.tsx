/**
 * OperationStatusBadge — exibe o estado operacional global.
 *
 * Reutiliza StatusBadge + mapeamento de OperationState → VisualStatus.
 * Acessível: ícone + texto + tooltip + ARIA.
 */

import { Circle, Play, Pause, AlertTriangle, XCircle, Loader2, CheckCircle2, Square } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import {
  operationStateToVisual,
  operationStateLabel,
  type OperationState,
} from "@/contexts/OperationContext";
import { cn } from "@/utils";

interface OperationStatusBadgeProps {
  state: OperationState;
  message?: string;
  since?: number;
  className?: string;
  /** Compacto: apenas ícone + dot. */
  compact?: boolean;
}

const STATE_ICON: Record<OperationState, typeof Circle> = {
  stopped: Square,
  starting: Loader2,
  ready: CheckCircle2,
  running: Play,
  paused: Pause,
  degraded: AlertTriangle,
  error: XCircle,
  stopping: Square,
};

export function OperationStatusBadge({
  state,
  message,
  since,
  className,
  compact = false,
}: OperationStatusBadgeProps) {
  const visual = operationStateToVisual(state);
  const label = operationStateLabel(state);
  const Icon = STATE_ICON[state];
  const tooltip = message
    ? `${label}: ${message}`
    : since
      ? `${label} desde ${new Date(since * 1000).toLocaleTimeString("pt-BR")}`
      : label;

  if (compact) {
    return (
      <span
        className={cn("inline-flex items-center", className)}
        title={tooltip}
        aria-label={`Estado operacional: ${label}`}
        role="status"
        data-testid="operation-status-badge"
        data-state={state}
      >
        <StatusBadge status={visual} showDot label={label} />
      </span>
    );
  }

  return (
    <span
      className={cn("inline-flex items-center gap-1.5", className)}
      title={tooltip}
      role="status"
      aria-label={`Estado operacional: ${label}`}
      data-testid="operation-status-badge"
      data-state={state}
    >
      <Icon
        className={cn(
          "h-4 w-4",
          state === "starting" || state === "stopping" ? "animate-spin" : "",
        )}
      />
      <StatusBadge status={visual} showDot label={label} />
    </span>
  );
}
