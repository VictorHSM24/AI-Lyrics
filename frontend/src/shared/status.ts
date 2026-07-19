/**
 * Status visuais reutilizáveis.
 *
 * Usados por StatusBadge, MetricCard, HealthCard, e qualquer
 * componente que precise indicar estado.
 */

export type VisualStatus =
  | "healthy"
  | "warning"
  | "error"
  | "offline"
  | "unknown"
  | "processing"
  | "paused"
  | "running"
  | "success"
  | "info";

export const VISUAL_STATUSES: VisualStatus[] = [
  "healthy",
  "warning",
  "error",
  "offline",
  "unknown",
  "processing",
  "paused",
  "running",
  "success",
  "info",
];

export interface StatusConfig {
  label: string;
  colorClass: string;
  dotClass: string;
  bgClass: string;
  borderClass: string;
}

export const STATUS_CONFIG: Record<VisualStatus, StatusConfig> = {
  healthy: {
    label: "Saudável",
    colorClass: "text-status-healthy",
    dotClass: "bg-status-healthy",
    bgClass: "bg-status-healthy/10",
    borderClass: "border-status-healthy/30",
  },
  warning: {
    label: "Atenção",
    colorClass: "text-status-warning",
    dotClass: "bg-status-warning",
    bgClass: "bg-status-warning/10",
    borderClass: "border-status-warning/30",
  },
  error: {
    label: "Erro",
    colorClass: "text-status-error",
    dotClass: "bg-status-error",
    bgClass: "bg-status-error/10",
    borderClass: "border-status-error/30",
  },
  offline: {
    label: "Offline",
    colorClass: "text-status-offline",
    dotClass: "bg-status-offline",
    bgClass: "bg-status-offline/10",
    borderClass: "border-status-offline/30",
  },
  unknown: {
    label: "Desconhecido",
    colorClass: "text-status-unknown",
    dotClass: "bg-status-unknown",
    bgClass: "bg-status-unknown/10",
    borderClass: "border-status-unknown/30",
  },
  processing: {
    label: "Processando",
    colorClass: "text-status-processing",
    dotClass: "bg-status-processing",
    bgClass: "bg-status-processing/10",
    borderClass: "border-status-processing/30",
  },
  paused: {
    label: "Pausado",
    colorClass: "text-status-paused",
    dotClass: "bg-status-paused",
    bgClass: "bg-status-paused/10",
    borderClass: "border-status-paused/30",
  },
  running: {
    label: "Executando",
    colorClass: "text-status-running",
    dotClass: "bg-status-running",
    bgClass: "bg-status-running/10",
    borderClass: "border-status-running/30",
  },
  success: {
    label: "Sucesso",
    colorClass: "text-status-success",
    dotClass: "bg-status-success",
    bgClass: "bg-status-success/10",
    borderClass: "border-status-success/30",
  },
  info: {
    label: "Informação",
    colorClass: "text-status-info",
    dotClass: "bg-status-info",
    bgClass: "bg-status-info/10",
    borderClass: "border-status-info/30",
  },
};

/**
 * Converte HealthStatus do backend para VisualStatus do frontend.
 */
export function healthToVisualStatus(
  health: "healthy" | "degraded" | "unhealthy" | "unknown",
): VisualStatus {
  switch (health) {
    case "healthy":
      return "healthy";
    case "degraded":
      return "warning";
    case "unhealthy":
      return "error";
    case "unknown":
      return "unknown";
  }
}
