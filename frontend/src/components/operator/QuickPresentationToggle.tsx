/**
 * QuickPresentationToggle (Sprint 25 Fase B) — toggle do modo quick.
 *
 * Quick presentation: envia versículo para o Holyrics como item
 * "rápido" sem encerrar a apresentação atual. Útil para mostrar
 * versículos de apoio sem interromper o fluxo principal.
 */

import { Zap } from "lucide-react";
import { cn } from "@/utils";

interface QuickPresentationToggleProps {
  value: boolean;
  onChange: (value: boolean) => void;
  className?: string;
}

export function QuickPresentationToggle({
  value,
  onChange,
  className,
}: QuickPresentationToggleProps) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={cn(
        "flex items-center justify-between gap-2 rounded-lg border px-4 py-3 transition-colors min-h-[44px]",
        value
          ? "border-status-warning/50 bg-status-warning/10"
          : "border-border bg-surface hover:bg-surface-hover",
        className,
      )}
      data-testid="quick-presentation-toggle"
      aria-pressed={value}
      aria-label="Alternar modo de apresentação rápida"
    >
      <span className="flex items-center gap-2">
        <Zap
          className={cn(
            "h-4 w-4 transition-colors",
            value ? "text-status-warning" : "text-text-muted",
          )}
        />
        <span className="text-sm font-medium text-text">Apresentação Rápida</span>
      </span>
      <span
        className={cn(
          "text-xs font-semibold px-2 py-0.5 rounded",
          value
            ? "bg-status-warning/20 text-status-warning"
            : "bg-surface-hover text-text-muted",
        )}
      >
        {value ? "ON" : "OFF"}
      </span>
    </button>
  );
}
