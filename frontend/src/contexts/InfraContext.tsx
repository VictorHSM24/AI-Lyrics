/**
 * InfraContext — provê Client SDK, EventStream, Stores, Services
 * e EventStreamBridge para toda a aplicação.
 *
 * Este context é a única ponte entre a infraestrutura reativa
 * e o React. Nenhum outro módulo deve instanciar essas
 * dependências diretamente.
 *
 * Por padrão, usa RealClient (REST + WebSocket) se a URL do
 * backend estiver disponível. Caso contrário, cai para o stub.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import {
  asClient,
  createClient,
  createRealClient,
  getDefaultClient,
  type Client,
} from "@/sdk";
import {
  createEventStream,
  createEventStreamBridge,
  type EventStream,
  type EventStreamBridge,
} from "@/stream";
import {
  createStoreRegistry,
  type StoreRegistry,
} from "@/stores";
import {
  createServices,
  type PresentationServices,
} from "@/services";

// ============================================================
// Infrastructure — bundle de dependências.
// ============================================================

export interface Infrastructure {
  readonly client: Client;
  readonly stream: EventStream;
  readonly stores: StoreRegistry;
  readonly services: PresentationServices;
  readonly bridge: EventStreamBridge;
}

// ============================================================
// Config — URL do backend.
// ============================================================

export interface InfraConfig {
  /** URL base da API REST (ex: "http://localhost:8000"). Se omitido, usa stub. */
  restUrl?: string;
  /** URL do WebSocket (ex: "ws://localhost:8000/ws/events"). Se omitido, WS não é usado. */
  wsUrl?: string;
  /** Auto-conectar ao montar. Padrão: true. */
  autoConnect?: boolean;
}

// ============================================================
// Context
// ============================================================

const InfraContext = createContext<Infrastructure | null>(null);

export interface InfraProviderProps {
  children: ReactNode;
  /** Override para testes. */
  client?: Client;
  stream?: EventStream;
  stores?: StoreRegistry;
  services?: PresentationServices;
  /** Configuração do backend. */
  config?: InfraConfig;
}

export function InfraProvider({
  children,
  client,
  stream,
  stores,
  services,
  config,
}: InfraProviderProps) {
  const infra = useMemo<Infrastructure>(() => {
    let c: Client;
    if (client) {
      c = client;
    } else if (config?.restUrl) {
      // RealClient com REST + WebSocket.
      const real = createRealClient({
        restUrl: config.restUrl,
        wsUrl: config.wsUrl,
      });
      c = asClient(real);
    } else {
      c = getDefaultClient();
    }
    const s = stream ?? createEventStream();
    const st = stores ?? createStoreRegistry();
    const sv = services ?? createServices(c);
    const br = createEventStreamBridge(c, s, st);
    return { client: c, stream: s, stores: st, services: sv, bridge: br };
  }, [client, stream, stores, services, config?.restUrl, config?.wsUrl]);

  // Inicia bridge e conecta ao backend.
  const bridgeStarted = useRef(false);
  useEffect(() => {
    if (bridgeStarted.current) return;
    bridgeStarted.current = true;
    infra.bridge.start();
    if (config?.autoConnect !== false && config?.restUrl) {
      infra.client.connect().then(() => {
        // Conexão bem-sucedida — ConnectionContext atualizará o status.
      }).catch(() => {
        // Erro de conexão — não bloqueia a UI.
        // ConnectionContext mostrará "disconnected".
      });
    }
    return () => {
      infra.bridge.stop();
    };
  }, [infra, config?.autoConnect, config?.restUrl]);

  return (
    <InfraContext.Provider value={infra}>
      {children}
    </InfraContext.Provider>
  );
}

export function useInfrastructure(): Infrastructure {
  const ctx = useContext(InfraContext);
  if (!ctx) {
    throw new Error(
      "useInfrastructure deve ser usado dentro de InfraProvider",
    );
  }
  return ctx;
}

// ============================================================
// Hooks de conveniência — acessam subpartes da infraestrutura.
// ============================================================

export function useClient(): Client {
  return useInfrastructure().client;
}

export function useEventStream(): EventStream {
  return useInfrastructure().stream;
}

export function useStores(): StoreRegistry {
  return useInfrastructure().stores;
}

export function useServices(): PresentationServices {
  return useInfrastructure().services;
}

export function useBridge(): EventStreamBridge {
  return useInfrastructure().bridge;
}

// ============================================================
// Helper para testes — cria infraestrutura isolada.
// ============================================================

export function createInfrastructure(): Infrastructure {
  const client = createClient();
  const stream = createEventStream();
  const stores = createStoreRegistry();
  const services = createServices(client);
  const bridge = createEventStreamBridge(client, stream, stores);
  return { client, stream, stores, services, bridge };
}
