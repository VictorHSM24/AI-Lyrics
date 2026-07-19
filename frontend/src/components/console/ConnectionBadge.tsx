/**
 * ConnectionBadge — badge de status da conexão com o backend.
 *
 * Mostra ícone + texto + tooltip. Nunca depende apenas de cor.
 */

import { Wifi, WifiOff, Loader2 } from "lucide-react";
import { useConnectionStatus } from "@/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import type { VisualStatus } from "@/shared/status";

export function ConnectionBadge() {
  const { status } = useConnectionStatus();

  const visual: VisualStatus =
    status === "connected" ? "success" :
    status === "connecting" ? "warning" :
    status === "disconnected" ? "error" :
    "unknown";

  const label =
    status === "connected" ? "Conectado" :
    status === "connecting" ? "Conectando" :
    status === "disconnected" ? "Desconectado" :
    "Desconhecido";

  const Icon =
    status === "connected" ? Wifi :
    status === "connecting" ? Loader2 :
    WifiOff;

  return (
    <div className="flex items-center gap-1.5" title={`Status: ${label}`}>
      <Icon
        className={`h-4 w-4 ${status === "connecting" ? "animate-spin" : ""}`}
        aria-hidden="true"
      />
      <StatusBadge status={visual} label={label} />
    </div>
  );
}
