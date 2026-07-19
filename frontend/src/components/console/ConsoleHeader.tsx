/**
 * ConsoleHeader — cabeçalho do Console Operacional.
 *
 * Mostra:
 * - Estado da conexão (ConnectionBadge)
 * - Estado do backend (HealthBadge)
 * - Sessão atual
 * - Tempo da sessão
 * - Pipeline (running/paused/stopped)
 * - Latência (LatencyBadge)
 * - Modelo STT ativo
 * - Idioma
 *
 * Dados vêm de Hooks (usePipeline, useSession, useConfiguration, useHealth).
 */

import { Activity, Clock, Mic2, Languages, Server } from "@/components/console/icons";
import { usePipeline, useSession, useConfiguration, useHealth } from "@/hooks";
import { ConnectionBadge } from "./ConnectionBadge";
import { LatencyBadge } from "./LatencyBadge";
import { StatusBadge } from "@/components/StatusBadge";
import type { VisualStatus } from "@/shared/status";

function formatDuration(seconds: number): string {
  if (seconds <= 0) return "00:00";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function ConsoleHeader() {
  const { status } = usePipeline();
  const { session } = useSession();
  const { configuration } = useConfiguration();
  const { health } = useHealth();

  const pipelineVisual: VisualStatus =
    status?.running ? "running" :
    status?.paused ? "paused" :
    "offline";

  const pipelineLabel =
    status?.running ? "Executando" :
    status?.paused ? "Pausado" :
    "Parado";

  const backendVisual: VisualStatus = health?.all_healthy ? "healthy" : "warning";
  const backendLabel = health?.all_healthy ? "Backend OK" : "Backend instável";

  const sttModel = (configuration?.stt["model"] as string) ?? "—";
  const sttLanguage = (configuration?.stt["language"] as string) ?? "pt-BR";
  const sessionId = session?.session_id ?? "—";
  const duration = session?.duration_s ?? 0;

  return (
    <div
      className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-surface px-4 py-3"
      data-testid="console-header"
    >
      {/* Conexão */}
      <ConnectionBadge />

      {/* Backend */}
      <div className="flex items-center gap-1.5" title={backendLabel}>
        <StatusBadge status={backendVisual} label={backendLabel} />
      </div>

      {/* Pipeline */}
      <div className="flex items-center gap-1.5" title={`Pipeline: ${pipelineLabel}`}>
        <Activity className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <StatusBadge status={pipelineVisual} label={pipelineLabel} />
      </div>

      {/* Latência */}
      <LatencyBadge />

      {/* Sessão */}
      <div className="flex items-center gap-1.5 text-sm" title={`Sessão: ${sessionId}`}>
        <Server className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <span className="text-text-muted">Sessão:</span>
        <span className="font-medium text-text" data-testid="session-id">
          {sessionId.slice(0, 12)}
        </span>
      </div>

      {/* Tempo */}
      <div className="flex items-center gap-1.5 text-sm" title={`Tempo: ${formatDuration(duration)}`}>
        <Clock className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <span className="text-text-muted">Tempo:</span>
        <span className="font-medium tabular-nums text-text" data-testid="session-duration">
          {formatDuration(duration)}
        </span>
      </div>

      {/* STT Modelo */}
      <div className="flex items-center gap-1.5 text-sm" title={`Modelo STT: ${sttModel}`}>
        <Mic2 className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <span className="text-text-muted">STT:</span>
        <span className="font-medium text-text">{sttModel}</span>
      </div>

      {/* Idioma */}
      <div className="flex items-center gap-1.5 text-sm" title={`Idioma: ${sttLanguage}`}>
        <Languages className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <span className="text-text-muted">Idioma:</span>
        <span className="font-medium text-text">{sttLanguage}</span>
      </div>
    </div>
  );
}
