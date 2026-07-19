/**
 * Transport — abstração de transporte de comunicação.
 *
 * O Client SDK consome Transport para falar com o backend.
 * Nenhum transporte real é implementado. Apenas os contratos.
 *
 * Tecnologias futuras (REST, WebSocket, SSE) implementarão
 * estes contratos sem que Hooks, Services ou Componentes
 * precisem ser modificados.
 */

import type { CancelToken } from "./cancel";
import type { PresentationError } from "./errors";
import type { Versioned } from "./versioning";

// ============================================================
// TransportStatus
// ============================================================

export type TransportStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

// ============================================================
// TransportEvent — eventos emitidos pelo transporte.
// ============================================================

export type TransportEvent =
  | { type: "status"; status: TransportStatus }
  | { type: "message"; payload: unknown }
  | { type: "error"; error: PresentationError };

export interface TransportListener {
  (event: TransportEvent): void;
}

// ============================================================
// Request / Response
// ============================================================

export interface TransportRequest {
  /** Identificador único da requisição. */
  readonly id: string;
  /** Nome do método/endpoint (ex: "pipeline.getStatus"). */
  readonly method: string;
  /** Argumentos nomeados. */
  readonly params: Record<string, unknown>;
  /** Token de cancelamento opcional. */
  readonly cancel?: CancelToken;
  /** Timeout em ms (0 = sem timeout). */
  readonly timeoutMs?: number;
}

export interface TransportResponse<T = unknown> {
  readonly id: string;
  readonly ok: true;
  readonly result: Versioned<T>;
}

export interface TransportErrorResponse {
  readonly id: string;
  readonly ok: false;
  readonly error: PresentationError;
}

export type TransportResult<T = unknown> = TransportResponse<T> | TransportErrorResponse;

// ============================================================
// Transport — contrato base.
// ============================================================

export interface Transport {
  /** Inicia a conexão (se aplicável). */
  open(): Promise<void>;
  /** Encerra a conexão. */
  close(): Promise<void>;
  /** Estado atual. */
  readonly status: TransportStatus;
  /** Registra listener de eventos do transporte. */
  subscribe(listener: TransportListener): () => void;
  /** Envia requisição e aguarda resposta. */
  request<T>(req: TransportRequest): Promise<TransportResult<T>>;
}

// ============================================================
// TransportFactory — função que cria um transporte.
// ============================================================

export interface TransportConfig {
  /** URL base do backend. */
  readonly url: string;
  /** Headers adicionais (futuro: auth). */
  readonly headers?: Record<string, string>;
  /** Timeout padrão em ms. */
  readonly defaultTimeoutMs?: number;
  /** Tentativas de reconexão (0 = sem retry). */
  readonly maxRetries?: number;
}

export type TransportFactory = (config: TransportConfig) => Transport;

// ============================================================
// Stub — transporte que sempre falha com "not configured".
// ============================================================

import { notConfigured } from "./errors";

export function createStubTransport(): Transport {
  const listeners: TransportListener[] = [];
  let status: TransportStatus = "idle";

  return {
    async open() {
      status = "disconnected";
      // Sem backend — apenas registra estado.
    },
    async close() {
      status = "disconnected";
    },
    get status() {
      return status;
    },
    subscribe(listener: TransportListener) {
      listeners.push(listener);
      return () => {
        const idx = listeners.indexOf(listener);
        if (idx >= 0) listeners.splice(idx, 1);
      };
    },
    async request<T>(_req: TransportRequest): Promise<TransportResult<T>> {
      return {
        id: _req.id,
        ok: false,
        error: notConfigured(),
      };
    },
  };
}
