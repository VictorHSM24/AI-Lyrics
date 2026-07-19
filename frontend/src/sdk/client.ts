/**
 * AI Lyrics Client SDK
 *
 * Camada intermediária entre Services e Transporte.
 *
 * Responsabilidades futuras:
 * - Serialização / desserialização
 * - Timeout
 * - Tratamento de erros
 * - Heartbeat
 * - Reconexão
 * - Cache
 * - Versionamento
 * - Autenticação futura
 * - Multiplexação de conexões
 *
 * Nenhuma implementação real de comunicação. Apenas contratos
 * e estrutura preparatória.
 *
 * Fluxo:
 *   Hooks → Services → Client SDK → Transport → (REST/WS/SSE)
 */

import type { CancelToken } from "./cancel";
import { NEVER_CANCEL } from "./cancel";
import {
  PresentationError,
  timeout as timeoutError,
  type ErrorCode,
} from "./errors";
import type {
  Transport,
  TransportConfig,
  TransportRequest,
  TransportResult,
  TransportEvent,
  TransportStatus,
} from "./transport";
import { createStubTransport } from "./transport";
import {
  CURRENT_API_VERSION,
  apiVersionToString,
  isCompatible,
  type ApiVersion,
  type Versioned,
} from "./versioning";

// ============================================================
// ClientConfig
// ============================================================

export interface ClientConfig {
  /** Configuração do transporte. */
  readonly transport: TransportConfig;
  /** Versão esperada da API. */
  readonly expectedApi?: ApiVersion;
  /** Timeout padrão (ms). */
  readonly defaultTimeoutMs?: number;
}

// ============================================================
// ClientEventListener — eventos do SDK.
// ============================================================

export type ClientEvent =
  | { type: "status"; status: TransportStatus }
  | { type: "error"; error: PresentationError }
  | { type: "event"; payload: unknown };

export interface ClientEventListener {
  (event: ClientEvent): void;
}

// ============================================================
// Client — contrato principal do SDK.
// ============================================================

export interface Client {
  /** Inicia o cliente (abre transporte). */
  connect(): Promise<void>;
  /** Encerra o cliente. */
  disconnect(): Promise<void>;
  /** Estado atual. */
  readonly status: TransportStatus;
  /** Versão da API esperada pelo cliente. */
  readonly expectedApiVersion: ApiVersion;
  /** Registra listener de eventos do SDK. */
  subscribe(listener: ClientEventListener): () => void;
  /** Executa chamada remota tipada. */
  call<T>(
    method: string,
    params: Record<string, unknown>,
    options?: CallOptions,
  ): Promise<Versioned<T>>;
}

// ============================================================
// CallOptions
// ============================================================

export interface CallOptions {
  cancel?: CancelToken;
  timeoutMs?: number;
}

// ============================================================
// ClientImpl — implementação concreta (sem backend real).
// ============================================================

let _reqIdCounter = 0;
function nextRequestId(): string {
  _reqIdCounter += 1;
  return `req-${_reqIdCounter}`;
}

export class ClientImpl implements Client {
  private readonly transport: Transport;
  private readonly expectedApi: ApiVersion;
  private readonly defaultTimeoutMs: number;
  private readonly listeners: ClientEventListener[] = [];
  private readonly transportSub: () => void;

  constructor(
    transport: Transport = createStubTransport(),
    config: Partial<ClientConfig> = {},
  ) {
    this.transport = transport;
    this.expectedApi = config.expectedApi ?? CURRENT_API_VERSION;
    this.defaultTimeoutMs = config.defaultTimeoutMs ?? 30000;
    this.transportSub = transport.subscribe((ev: TransportEvent) => {
      this.handleTransportEvent(ev);
    });
  }

  get status(): TransportStatus {
    return this.transport.status;
  }

  get expectedApiVersion(): ApiVersion {
    return this.expectedApi;
  }

  async connect(): Promise<void> {
    await this.transport.open();
  }

  async disconnect(): Promise<void> {
    this.transportSub();
    await this.transport.close();
  }

  subscribe(listener: ClientEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  async call<T>(
    method: string,
    params: Record<string, unknown>,
    options: CallOptions = {},
  ): Promise<Versioned<T>> {
    const cancel = options.cancel ?? NEVER_CANCEL;
    cancel.throwIfCanceled();

    const timeoutMs = options.timeoutMs ?? this.defaultTimeoutMs;
    const req: TransportRequest = {
      id: nextRequestId(),
      method,
      params,
      cancel,
      timeoutMs,
    };

    // Timeout via Promise.race (preparação; sem backend real).
    const result = await this.raceWithTimeout<T>(this.transport.request<T>(req), timeoutMs, req.id);
    cancel.throwIfCanceled();

    if (!result.ok) {
      throw result.error;
    }

    // Validação de versão.
    if (!isCompatible(result.result, this.expectedApi)) {
      throw new PresentationError({
        code: "SDK_VERSION_MISMATCH" satisfies ErrorCode,
        message: `Versão incompatível: esperada ${apiVersionToString(this.expectedApi)}, ` +
          `recebida ${apiVersionToString(result.result.api)}.`,
        recoverable: false,
        severity: "high",
        details: {
          expected: apiVersionToString(this.expectedApi),
          received: apiVersionToString(result.result.api),
        },
      });
    }

    return result.result;
  }

  private raceWithTimeout<T>(
    promise: Promise<TransportResult<T>>,
    ms: number,
    reqId: string,
  ): Promise<TransportResult<T>> {
    if (ms <= 0) return promise;
    return new Promise<TransportResult<T>>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(timeoutError(ms, reqId));
      }, ms);
      promise.then(
        (r) => {
          clearTimeout(timer);
          resolve(r);
        },
        (e) => {
          clearTimeout(timer);
          reject(e);
        },
      );
    });
  }

  private handleTransportEvent(ev: TransportEvent): void {
    let mapped: ClientEvent | null = null;
    switch (ev.type) {
      case "status":
        mapped = { type: "status", status: ev.status };
        break;
      case "message":
        mapped = { type: "event", payload: ev.payload };
        break;
      case "error":
        mapped = { type: "error", error: ev.error };
        break;
    }
    if (!mapped) return;
    for (const l of this.listeners) {
      try {
        l(mapped);
      } catch {
        // Listeners não devem propagar erros.
      }
    }
  }
}

// ============================================================
// Factory
// ============================================================

export function createClient(config?: Partial<ClientConfig>): Client {
  const transport = createStubTransport();
  return new ClientImpl(transport, config);
}

// ============================================================
// Default client — singleton preguiço (sem backend).
// ============================================================

let _defaultClient: Client | null = null;

export function getDefaultClient(): Client {
  if (!_defaultClient) {
    _defaultClient = createClient();
  }
  return _defaultClient;
}

export function setDefaultClient(client: Client): void {
  _defaultClient = client;
}

// ============================================================
// Re-export de tipos públicos do SDK.
// ============================================================

export type { Transport, TransportConfig, TransportStatus } from "./transport";
export { PresentationError } from "./errors";
export { CURRENT_API_VERSION, apiVersionToString } from "./versioning";
