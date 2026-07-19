/**
 * StartupStep — exibe uma etapa da inicialização.
 *
 * Estados: pending, running, success, warning, error.
 * Acessível: ícone + texto + tooltip + ARIA.
 */

import {
  Circle,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from "lucide-react";
import type { StartupStep, StartupStepState } from "@/contexts/OperationContext";
import { cn } from "@/utils";

const STEP_CONFIG: Record<
  StartupStepState,
  { icon: typeof Circle; color: string; label: string }
> = {
  pending: { icon: Circle, color: "text-text-subtle", label: "Pendente" },
  running: { icon: Loader2, color: "text-status-processing", label: "Executando" },
  success: { icon: CheckCircle2, color: "text-status-success", label: "OK" },
  warning: { icon: AlertTriangle, color: "text-status-warning", label: "Atenção" },
  error: { icon: XCircle, color: "text-status-error", label: "Erro" },
};

interface StartupStepRowProps {
  step: StartupStep;
}

export function StartupStepRow({ step }: StartupStepRowProps) {
  const config = STEP_CONFIG[step.state];
  const Icon = config.icon;
  const tooltip = step.message
    ? `${step.label}: ${step.message}`
    : `${step.label}: ${config.label}${
        step.durationMs ? ` (${step.durationMs}ms)` : ""
      }`;

  return (
    <div
      className="flex items-center gap-3 py-1.5"
      data-testid="startup-step"
      data-step-id={step.id}
      data-state={step.state}
      title={tooltip}
      aria-label={`Etapa ${step.label}: ${config.label}`}
      role="status"
    >
      <Icon
        className={cn(
          "h-4 w-4 shrink-0",
          config.color,
          step.state === "running" ? "animate-spin" : "",
        )}
      />
      <span
        className={cn(
          "flex-1 text-sm",
          step.state === "pending" ? "text-text-muted" : "text-text",
        )}
      >
        {step.label}
      </span>
      {step.durationMs !== undefined && step.state !== "pending" && (
        <span className="text-xs text-text-subtle">{step.durationMs}ms</span>
      )}
      <span className={cn("text-xs font-medium", config.color)}>
        {config.label}
      </span>
    </div>
  );
}
