/**
 * HealthPanel — painel reutilizável de Saúde do sistema.
 *
 * Mostra status de cada componente:
 * Backend, Presentation, WebSocket, EventStream, Pipeline,
 * Microfone, STT, Busca Bíblica, Holyrics.
 *
 * Cada item: ícone + texto + tooltip + status (online/offline/inicializando/erro/degradado).
 *
 * Fonte dos dados: HealthSnapshot do store (polling real a cada 10s) +
 * ConnectionStatus para WebSocket/Backend.
 *
 * Sprint 15.2: status baseado em verificações reais do backend,
 * não em estado interno ou configuração carregada.
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
import type { VisualStatus } from "@/shared/status";
import { STATUS_CONFIG } from "@/shared/status";
import { cn } from "@/utils";

export type HealthItemStatus = "online" | "offline" | "initializing" | "error" | "degraded";

interface HealthItemDef {
  id: string;
  /** Nome do componente no backend HealthDTO (ou null se derivado do frontend). */
  backendComponent: string | null;
  label: string;
  icon: LucideIcon;
  description: string;
}

const HEALTH_ITEMS: HealthItemDef[] = [
  { id: "backend", backendComponent: "backend", label: "Backend", icon: Server, description: "Servidor FastAPI" },
  { id: "presentation", backendComponent: null, label: "Presentation", icon: Presentation, description: "Camada de apresentação" },
  { id: "websocket", backendComponent: "websocket", label: "WebSocket", icon: Radio, description: "Conexão WebSocket" },
  { id: "eventstream", backendComponent: "eventstream", label: "EventStream", icon: Activity, description: "Fluxo de eventos" },
  { id: "pipeline", backendComponent: "pipeline", label: "Pipeline", icon: GitBranch, description: "Pipeline de reconhecimento" },
  { id: "microphone", backendComponent: "microphone", label: "Microfone", icon: Mic, description: "Dispositivo de áudio" },
  { id: "stt", backendComponent: "speech_recognition", label: "STT", icon: AudioWaveform, description: "Speech-to-Text" },
  { id: "bible", backendComponent: "searcher", label: "Busca Bíblica", icon: BookOpen, description: "Busca de versículos" },
  { id: "holyrics", backendComponent: "holyrics", label: "Holyrics", icon: Church, description: "Integração Holyrics" },
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

/**
 * Deriva o status do item a partir do HealthDTO do backend.
 * Usa o campo `status` (healthy/degraded/unhealthy/unknown) e o campo `message`
 * como reason/description.
 *
 * Para componentes frontend-only (presentation), deriva do connection status.
 */
function deriveStatus(
  item: HealthItemDef,
  connStatus: string,
  healthComponents: Array<{ component: string; status: string; message: string }>,
): { status: HealthItemStatus; reason: string } {
  // Presentation — derivado do backend (se backend saudável, presentation também).
  if (item.id === "presentation") {
    if (connStatus === "connected") return { status: "online", reason: "Presentation operacional" };
    if (connStatus === "connecting" || connStatus === "reconnecting") return { status: "initializing", reason: "Conectando…" };
    return { status: "offline", reason: "Backend desconectado" };
  }

  // Para componentes do backend, usar o HealthDTO real.
  if (item.backendComponent) {
    const comp = healthComponents.find(
      (c) => c.component === item.backendComponent,
    );
    if (comp) {
      const reason = comp.message || item.description;
      if (comp.status === "healthy") return { status: "online", reason };
      if (comp.status === "degraded") return { status: "degraded", reason };
      if (comp.status === "unhealthy") return { status: "error", reason };
      if (comp.status === "unknown") return { status: "offline", reason };
      return { status: "initializing", reason };
    }
    // Componente não encontrado no health snapshot — offline.
    return { status: "offline", reason: "Componente não reportado pelo backend" };
  }

  return { status: "offline", reason: "Sem dados" };
}

interface HealthPanelProps {
  /** Compacto: apenas ícones + dots, sem descrição. */
  compact?: boolean;
  className?: string;
}

export function HealthPanel({ compact = false, className }: HealthPanelProps) {
  const { health } = useHealth();
  const { status: connStatus } = useConnection();

  const components = health?.components ?? [];

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
        const { status, reason } = deriveStatus(item, connStatus, components);
        const visual = healthItemStatusToVisual(status);
        const config = STATUS_CONFIG[visual];
        const Icon = item.icon;
        const tooltip = `${item.label}: ${config.label} — ${reason}`;

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
                <>
                  <span className={cn("text-xs", config.colorClass)}>
                    {config.label}
                  </span>
                  <span className="truncate text-[10px] text-text-subtle" title={reason}>
                    {reason}
                  </span>
                </>
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
