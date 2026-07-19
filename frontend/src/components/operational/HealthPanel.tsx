/**
 * HealthPanel — painel reutilizável de Saúde do sistema.
 *
 * Mostra status de cada componente:
 * Backend, Presentation, WebSocket, EventStream, Pipeline,
 * Microfone, STT, Busca Bíblica, Holyrics.
 *
 * Cada item: ícone + texto + tooltip + status (online/offline/inicializando/erro/degradado).
 *
 * Fonte dos dados: HealthSnapshot do store existente + ConnectionStatus.
 * Não acessa transporte diretamente.
 */

import {
  Server,
  Presentation,
  Radio,
  Activity,
  GitBranch,
  Mic,
  AudioWaveform,
  BookOpen,
  Church,
  type LucideIcon,
} from "lucide-react";
import { useHealth } from "@/hooks";
import { useConnection } from "@/contexts/ConnectionContext";
import { usePipeline } from "@/hooks";
import { useOperationState } from "@/contexts/OperationContext";
import type { VisualStatus } from "@/shared/status";
import { STATUS_CONFIG } from "@/shared/status";
import { cn } from "@/utils";

export type HealthItemStatus = "online" | "offline" | "initializing" | "error" | "degraded";

interface HealthItemDef {
  id: string;
  label: string;
  icon: LucideIcon;
  description: string;
}

const HEALTH_ITEMS: HealthItemDef[] = [
  { id: "backend", label: "Backend", icon: Server, description: "Servidor FastAPI" },
  { id: "presentation", label: "Presentation", icon: Presentation, description: "Camada de apresentação" },
  { id: "websocket", label: "WebSocket", icon: Radio, description: "Conexão WebSocket" },
  { id: "eventstream", label: "EventStream", icon: Activity, description: "Fluxo de eventos" },
  { id: "pipeline", label: "Pipeline", icon: GitBranch, description: "Pipeline de reconhecimento" },
  { id: "microphone", label: "Microfone", icon: Mic, description: "Dispositivo de áudio" },
  { id: "stt", label: "STT", icon: AudioWaveform, description: "Speech-to-Text" },
  { id: "bible", label: "Busca Bíblica", icon: BookOpen, description: "Busca de versículos" },
  { id: "holyrics", label: "Holyrics", icon: Church, description: "Integração Holyrics" },
];

function healthItemStatusToVisual(s: HealthItemStatus): VisualStatus {
  switch (s) {
    case "online": return "healthy";
    case "offline": return "offline";
    case "initializing": return "processing";
    case "error": return "error";
    case "degraded": return "warning";
  }
}

function deriveStatus(
  itemId: string,
  connStatus: string,
  healthComponents: Array<{ component: string; status: string }>,
  pipelineRunning: boolean,
  hasAudio: boolean,
): HealthItemStatus {
  // Backend / WebSocket dependem da conexão.
  if (itemId === "backend" || itemId === "websocket") {
    if (connStatus === "connected") return "online";
    if (connStatus === "connecting" || connStatus === "reconnecting") return "initializing";
    if (connStatus === "disconnected") return "offline";
    return "offline";
  }
  // Presentation / EventStream — derivam do backend.
  if (itemId === "presentation" || itemId === "eventstream") {
    if (connStatus === "connected") return "online";
    if (connStatus === "connecting") return "initializing";
    return "offline";
  }
  // Pipeline — deriva do estado do pipeline.
  if (itemId === "pipeline") {
    if (connStatus !== "connected") return "offline";
    return pipelineRunning ? "online" : "degraded";
  }
  // Microfone — depende de áudio estar configurado.
  if (itemId === "microphone") {
    return hasAudio ? "online" : "offline";
  }
  // Componentes do health snapshot.
  const comp = healthComponents.find(
    (c) => c.component === itemId || c.component.toLowerCase() === itemId.toLowerCase(),
  );
  if (comp) {
    if (comp.status === "healthy") return "online";
    if (comp.status === "degraded") return "degraded";
    if (comp.status === "unhealthy") return "error";
    return "initializing";
  }
  // Sem dados — offline.
  return "offline";
}

interface HealthPanelProps {
  /** Compacto: apenas ícones + dots, sem descrição. */
  compact?: boolean;
  className?: string;
}

export function HealthPanel({ compact = false, className }: HealthPanelProps) {
  const { health } = useHealth();
  const { status: connStatus } = useConnection();
  const { status: pipelineStatus } = usePipeline();
  const { settings } = useOperationState();

  const components = health?.components ?? [];
  const hasAudio = Boolean(settings?.data.audio.selectedDeviceId);
  const pipelineRunning = Boolean(pipelineStatus?.running);

  return (
    <div
      className={cn(
        "grid gap-2",
        compact ? "grid-cols-3" : "grid-cols-2 sm:grid-cols-3",
        className,
      )}
      data-testid="health-panel"
      role="list"
      aria-label="Saúde dos componentes"
    >
      {HEALTH_ITEMS.map((item) => {
        const status = deriveStatus(
          item.id,
          connStatus,
          components,
          pipelineRunning,
          hasAudio,
        );
        const visual = healthItemStatusToVisual(status);
        const config = STATUS_CONFIG[visual];
        const Icon = item.icon;
        const tooltip = `${item.label}: ${config.label} — ${item.description}`;

        return (
          <div
            key={item.id}
            className={cn(
              "flex items-center gap-2 rounded-md border px-3 py-2",
              config.borderClass,
              config.bgClass,
            )}
            data-testid="health-item"
            data-item-id={item.id}
            data-status={status}
            title={tooltip}
            role="listitem"
            aria-label={tooltip}
          >
            <Icon className={cn("h-4 w-4 shrink-0", config.colorClass)} />
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-xs font-medium text-text">
                {item.label}
              </span>
              {!compact && (
                <span className={cn("text-xs", config.colorClass)}>
                  {config.label}
                </span>
              )}
            </div>
            <span
              className={cn("ml-auto h-2 w-2 rounded-full", config.dotClass)}
              aria-hidden="true"
            />
          </div>
        );
      })}
    </div>
  );
}
