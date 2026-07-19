/**
 * ConnectionIndicator — mostra status real da conexão com o backend.
 *
 * Este é um componente de infraestrutura que exibe:
 * - Status da conexão (connected, disconnected, connecting, unknown)
 * - Timestamp da última conexão
 *
 * NÃO exibe dados de negócio — apenas indicadores de infraestrutura.
 */

import { useConnection } from "@/contexts/ConnectionContext";
import { StatusBadge } from "@/components";
import type { VisualStatus } from "@/shared/status";

export function ConnectionIndicator() {
  const { status, lastConnectedAt, transportStatus } = useConnection();

  const visualStatus: VisualStatus =
    status === "connected" ? "success" :
    status === "connecting" ? "warning" :
    status === "disconnected" ? "error" :
    "unknown";

  const label =
    status === "connected" ? "Backend conectado" :
    status === "connecting" ? "Conectando..." :
    status === "disconnected" ? "Backend desconectado" :
    "Status desconhecido";

  return (
    <div className="flex items-center gap-3 text-sm">
      <StatusBadge status={visualStatus} label={label} />
      {transportStatus === "reconnecting" && (
        <span className="text-status-warning">Reconectando</span>
      )}
      {lastConnectedAt > 0 && status === "connected" && (
        <span className="text-muted">
          Última conexão: {new Date(lastConnectedAt * 1000).toLocaleTimeString()}
        </span>
      )}
    </div>
  );
}
