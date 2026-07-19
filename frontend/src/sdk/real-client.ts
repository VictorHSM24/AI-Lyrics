/**
 * RealClient — Client SDK que usa REST + WebSocket reais.
 *
 * Combina:
 * - RestTransport para consultas (request/response)
 * - WebSocketTransport para eventos (server push)
 *
 * O RealClient orquestra ambos os transportes. Eventos recebidos
 * via WebSocket são repassados para os listeners do Client como
 * `ClientEvent` do tipo `event`.
 *
 * Nenhuma mudança na interface pública `Client` — o RealClient
 * implementa exatamente o mesmo contrato que o stub.
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
  TransportEvent,
  TransportRequest,
  TransportResult,
  TransportStatus,
} from "./transport";
import {
  CURRENT_API_VERSION,
  apiVersionToString,
  isCompatible,
  type ApiVersion,
  type Versioned,
} from "./versioning";
import {
  createRestTransport,
  createWebSocketTransport,
  type RestTransportOptions,
  type WebSocketTransportOptions,
} from "./transports";

// ============================================================
// ClientEvent / ClientEventListener (re-export)
// ============================================================

export type ClientEvent =
  | { type: "status"; status: TransportStatus }
  | { type: "error"; error: PresentationError }
  | { type: "event"; payload: unknown };

export interface ClientEventListener {
  (event: ClientEvent): void;
}

// ============================================================
// CallOptions
// ============================================================

export interface CallOptions {
  cancel?: CancelToken;
  timeoutMs?: number;
}

// ============================================================
// RealClientConfig
// ============================================================

export interface RealClientConfig {
  /** URL base da API REST (ex: "http://localhost:8000"). */
  restUrl: string;
  /** URL do WebSocket (ex: "ws://localhost:8000/ws/events"). Se omitido, WS não é usado. */
  wsUrl?: string;
  /** Versão esperada da API. */
  expectedApi?: ApiVersion;
  /** Timeout padrão (ms). */
  defaultTimeoutMs?: number;
  /** Headers adicionais. */
  headers?: Record<string, string>;
  /** Opções do RestTransport. */
  restOptions?: RestTransportOptions;
  /** Opções do WebSocketTransport. */
  wsOptions?: WebSocketTransportOptions;
}

// ============================================================
// RealClient
// ============================================================

let _reqIdCounter = 0;
function nextRequestId(): string {
  _reqIdCounter += 1;
  return `req-${_reqIdCounter}`;
}

export class RealClient {
  private readonly restTransport: Transport;
  private readonly wsTransport: Transport | null;
  private readonly expectedApi: ApiVersion;
  private readonly defaultTimeoutMs: number;
  private readonly listeners: ClientEventListener[] = [];
  private readonly restSub: () => void;
  private readonly wsSub: (() => void) | null = null;

  constructor(config: RealClientConfig) {
    this.expectedApi = config.expectedApi ?? CURRENT_API_VERSION;
    this.defaultTimeoutMs = config.defaultTimeoutMs ?? 30000;

    // REST Transport (sempre presente).
    this.restTransport = createRestTransport(
      { url: config.restUrl, headers: config.headers, defaultTimeoutMs: this.defaultTimeoutMs },
      config.restOptions,
    );
    this.restSub = this.restTransport.subscribe((ev: TransportEvent) => this.handleTransportEvent(ev, "rest"));

    // WebSocket Transport (opcional).
    if (config.wsUrl) {
      this.wsTransport = createWebSocketTransport(
        { url: config.wsUrl, headers: config.headers, defaultTimeoutMs: this.defaultTimeoutMs },
        config.wsOptions,
      );
      this.wsSub = this.wsTransport.subscribe((ev: TransportEvent) => this.handleTransportEvent(ev, "ws"));
    } else {
      this.wsTransport = null;
    }
  }

  get status(): TransportStatus {
    // Status é "connected" se REST está conectado.
    // WebSocket pode estar reconectando — não afeta consultas.
    return this.restTransport.status;
  }

  get wsStatus(): TransportStatus {
    return this.wsTransport?.status ?? "idle";
  }

  get expectedApiVersion(): ApiVersion {
    return this.expectedApi;
  }

  async connect(): Promise<void> {
    // Abre REST (não-bloqueante — REST não tem conexão persistente).
    await this.restTransport.open();
    // Abre WebSocket (se configurado).
    if (this.wsTransport) {
      await this.wsTransport.open();
    }
  }

  async disconnect(): Promise<void> {
    this.restSub();
    if (this.wsSub) this.wsSub();
    await this.restTransport.close();
    if (this.wsTransport) {
      await this.wsTransport.close();
    }
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

    const result = await this.raceWithTimeout<T>(
      this.restTransport.request<T>(req),
      timeoutMs,
      req.id,
    );
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

  private handleTransportEvent(ev: TransportEvent, source: "rest" | "ws"): void {
    let mapped: ClientEvent | null = null;
    switch (ev.type) {
      case "status":
        // Só emite status do REST como status principal do client.
        // Status do WS é emitido como evento para listeners interessados.
        if (source === "rest") {
          mapped = { type: "status", status: ev.status };
        } else {
          // WS status — emite como evento para listeners.
          mapped = { type: "status", status: ev.status };
        }
        break;
      case "message":
        // Mensagens do WebSocket são eventos.
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
        // listeners não propagam erros
      }
    }
  }
}

// ============================================================
// Factory
// ============================================================

export function createRealClient(config: RealClientConfig): RealClient {
  return new RealClient(config);
}

// ============================================================
// Adapter — RealClient como Client (compatibilidade de interface).
// ============================================================

import type { Client } from "./client";

/**
 * Adapta um RealClient para a interface Client.
 *
 * Permite que o RealClient seja usado em qualquer lugar que
 * espera um Client (ex: InfraProvider, createServices).
 */
export function asClient(real: RealClient): Client {
  return {
    connect: () => real.connect(),
    disconnect: () => real.disconnect(),
    get status() { return real.status; },
    get expectedApiVersion() { return real.expectedApiVersion; },
    subscribe: (l) => real.subscribe(l as ClientEventListener),
    call: <T>(method: string, params: Record<string, unknown>, options?: CallOptions) =>
      real.call<T>(method, params, options),
  };
}
