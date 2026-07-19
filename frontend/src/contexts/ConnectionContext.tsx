import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useClient } from "./InfraContext";
import type { TransportStatus } from "@/sdk";

export type ConnectionStatus = "connected" | "disconnected" | "connecting" | "unknown";

export interface ConnectionContextValue {
  status: ConnectionStatus;
  /** URL do backend. */
  backendUrl: string;
  /** Timestamp da última conexão bem-sucedida (0 se nunca). */
  lastConnectedAt: number;
  /** Status detalhado do transporte (inclui "reconnecting" e "error"). */
  transportStatus: TransportStatus;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const client = useClient();
  const [status, setStatus] = useState<ConnectionStatus>("unknown");
  const [transportStatus, setTransportStatus] = useState<TransportStatus>(client.status);
  const [lastConnectedAt, setLastConnectedAt] = useState(0);

  // Assina mudanças de status do Client SDK.
  useEffect(() => {
    const unsub = client.subscribe((event) => {
      if (event.type === "status") {
        setTransportStatus(event.status);
        const mapped: ConnectionStatus =
          event.status === "connected" ? "connected" :
          event.status === "connecting" ? "connecting" :
          event.status === "reconnecting" ? "connecting" :
          event.status === "disconnected" ? "disconnected" :
          "unknown";
        setStatus(mapped);
        if (event.status === "connected") {
          setLastConnectedAt(Date.now() / 1000);
        }
      }
    });
    // Status inicial.
    setTransportStatus(client.status);
    return () => unsub();
  }, [client]);

  const value: ConnectionContextValue = {
    status,
    backendUrl: "http://localhost:8000",
    lastConnectedAt,
    transportStatus,
  };

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection(): ConnectionContextValue {
  const ctx = useContext(ConnectionContext);
  if (!ctx) {
    throw new Error("useConnection deve ser usado dentro de ConnectionProvider");
  }
  return ctx;
}
