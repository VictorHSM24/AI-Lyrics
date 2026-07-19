/**
 * LatencyBadge — badge de latência média do pipeline.
 *
 * Mostra ícone + valor + tooltip. Cor varia conforme a latência.
 */

import { Clock } from "lucide-react";
import { useMetrics } from "@/hooks";
import { cn } from "@/utils";

export function LatencyBadge() {
  const { metrics } = useMetrics();
  const latency = metrics?.avg_latency_ms ?? 0;

  const colorClass =
    latency === 0 ? "text-text-subtle" :
    latency < 500 ? "text-status-healthy" :
    latency < 2000 ? "text-status-warning" :
    "text-status-error";

  const label =
    latency === 0 ? "—" :
    latency < 1000 ? `${Math.round(latency)} ms` :
    `${(latency / 1000).toFixed(1)} s`;

  return (
    <div
      className="flex items-center gap-1.5 text-sm"
      title={`Latência média: ${label}`}
    >
      <Clock className="h-4 w-4 text-text-muted" aria-hidden="true" />
      <span className={cn("font-medium", colorClass)} data-testid="latency-badge">
        {label}
      </span>
    </div>
  );
}
