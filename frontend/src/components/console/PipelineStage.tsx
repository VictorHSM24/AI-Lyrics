/**
 * PipelineStage — etapa individual do pipeline.
 *
 * Mostra o nome da etapa e seu estado visual:
 * Idle, Running, Success, Warning, Error.
 *
 * Nunca depende apenas de cor — sempre tem ícone + texto.
 */

import {
  Circle, Loader2, CheckCircle, AlertTriangle, XCircle,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/utils";

export type StageState = "idle" | "running" | "success" | "warning" | "error";

interface PipelineStageProps {
  name: string;
  state: StageState;
  /** Tempo opcional (ms) que a etapa levou. */
  latencyMs?: number;
  className?: string;
}

const STATE_CONFIG: Record<StageState, {
  label: string;
  colorClass: string;
  bgClass: string;
  borderClass: string;
  icon: LucideIcon;
  spin?: boolean;
}> = {
  idle: {
    label: "Aguardando",
    colorClass: "text-text-subtle",
    bgClass: "bg-surface",
    borderClass: "border-border",
    icon: Circle,
  },
  running: {
    label: "Executando",
    colorClass: "text-status-processing",
    bgClass: "bg-status-processing/10",
    borderClass: "border-status-processing/30",
    icon: Loader2,
    spin: true,
  },
  success: {
    label: "Concluído",
    colorClass: "text-status-healthy",
    bgClass: "bg-status-healthy/10",
    borderClass: "border-status-healthy/30",
    icon: CheckCircle,
  },
  warning: {
    label: "Atenção",
    colorClass: "text-status-warning",
    bgClass: "bg-status-warning/10",
    borderClass: "border-status-warning/30",
    icon: AlertTriangle,
  },
  error: {
    label: "Erro",
    colorClass: "text-status-error",
    bgClass: "bg-status-error/10",
    borderClass: "border-status-error/30",
    icon: XCircle,
  },
};

export function PipelineStage({ name, state, latencyMs, className }: PipelineStageProps) {
  const config = STATE_CONFIG[state];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border px-3 py-2",
        config.bgClass,
        config.borderClass,
        className,
      )}
      data-testid="pipeline-stage"
      data-stage={name}
      data-state={state}
      title={`${name}: ${config.label}${latencyMs != null ? ` (${Math.round(latencyMs)} ms)` : ""}`}
    >
      <Icon
        className={cn("h-4 w-4 shrink-0", config.colorClass, config.spin && "animate-spin")}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-xs font-medium text-text">{name}</span>
        <span className={cn("text-xs", config.colorClass)}>
          {config.label}
          {latencyMs != null && latencyMs > 0 && (
            <span className="text-text-subtle"> · {Math.round(latencyMs)} ms</span>
          )}
        </span>
      </div>
    </div>
  );
}
