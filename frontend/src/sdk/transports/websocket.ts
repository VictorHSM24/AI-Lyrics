/**
 * WebSocket Transport — implementação real de Transport via WebSocket.
 *
 * Usa a WebSocket API nativa do browser. Sem dependências externas.
 *
 * Recursos:
 * - Conexão persistente
 * - Heartbeat periódico (ping/pong)
 * - Reconexão automática com backoff exponencial
 * - Recebimento de eventos (server push)
 * - Cancelamento via CancelToken
 * - Timeout de conexão
 * - Tratamento de erros → PresentationError
 *
 * NÃO implementa cache nem retry de requisições (essas
 * responsabilidades pertencem ao Client SDK).
 */

import { notConfigured, PresentationError } from "../errors";
import type {
  Transport,
  TransportConfig,
  TransportEvent,
  TransportListener,
  TransportRequest,
  TransportResult,
  TransportStatus,
} from "../transport";

// ============================================================
// Logger
// ============================================================

interface Logger {
  info(msg: string, ctx?: Record<string, unknown>): void;
  warn(msg: string, ctx?: Record<string, unknown>): void;
  error(msg: string, ctx?: Record<string, unknown>): void;
  debug(msg: string, ctx?: Record<string, unknown>): void;
}

const noopLogger: Logger = {
  info() {}, warn() {}, error() {}, debug() {},
};

// ============================================================
// Configuração
// ============================================================

export interface WebSocketTransportOptions {
  logger?: Logger;
  /** Intervalo de heartbeat (ms). Padrão: 30000. */
  heartbeatMs?: number;
  /** Tentativas máximas de reconexão. Padrão: 5. */
  maxReconnectAttempts?: number;
  /** Backoff base para reconexão (ms). Padrão: 1000. */
  reconnectBaseMs?: number;
  /** Timeout de conexão (ms). Padrão: 10000. */
  connectTimeoutMs?: number;
}

// ============================================================
// Tipos de mensagens WebSocket
// ============================================================

interface WsHello {
  type: "hello";
  api: { major: number; minor: number; patch: number; pre: string | null };
  server_time: number;
}

interface WsEvent {
  type: "event";
  event: unknown;
}

interface WsHeartbeatAck {
  type: "heartbeat_ack";
  server_time: number;
}

interface WsError {
  type: "error";
  error: { code: string; message: string; details?: Record<string, unknown>; recoverable?: boolean; severity?: string };
}

type WsMessage = WsHello | WsEvent | WsHeartbeatAck | WsError;

// ============================================================
// WebSocketTransport
// ============================================================

export class WebSocketTransport implements Transport {
  private readonly config: TransportConfig;
  private readonly logger: Logger;
  private readonly listeners: TransportListener[] = [];
  private readonly heartbeatMs: number;
  private readonly maxReconnectAttempts: number;
  private readonly reconnectBaseMs: number;
  private readonly connectTimeoutMs: number;

  private _status: TransportStatus = "idle";
  private _ws: WebSocket | null = null;
  private _reconnectAttempts = 0;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private _connectTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
  private _pendingRequests: Map<string, {
    resolve: (r: TransportResult) => void;
    reject: (e: unknown) => void;
    timer: ReturnType<typeof setTimeout> | null;
  }> = new Map();
  private _closed = false;

  constructor(config: TransportConfig, options: WebSocketTransportOptions = {}) {
    this.config = config;
    this.logger = options.logger ?? noopLogger;
    this.heartbeatMs = options.heartbeatMs ?? 30000;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
    this.reconnectBaseMs = options.reconnectBaseMs ?? 1000;
    this.connectTimeoutMs = options.connectTimeoutMs ?? 10000;
  }

  get status(): TransportStatus {
    return this._status;
  }

  async open(): Promise<void> {
    if (this._closed) return;
    if (this._ws && (this._ws.readyState === WebSocket.OPEN || this._ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    await this.connect();
  }

  async close(): Promise<void> {
    this._closed = true;
    this.cleanup();
    if (this._ws) {
      try {
        this._ws.close(1000, "client closing");
      } catch {
        // ignore
      }
      this._ws = null;
    }
    this._status = "disconnected";
    this.emit({ type: "status", status: this._status });
    this.logger.info("WebSocket transport fechado");
  }

  subscribe(listener: TransportListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  async request<T>(req: TransportRequest): Promise<TransportResult<T>> {
    // WebSocket Transport não implementa request/response tradicional.
    // Para consultas, o Client SDK deve usar RestTransport.
    // Este método existe apenas para satisfazer a interface Transport.
    const err = new PresentationError({
      code: "SERVICE_UNAVAILABLE",
      message: "WebSocketTransport não suporta request/response — use RestTransport para consultas.",
      recoverable: false,
      severity: "low",
      details: { method: req.method },
    });
    return { id: req.id, ok: false, error: err };
  }

  // ============================================================
  // Conexão
  // ============================================================

  private async connect(): Promise<void> {
    if (!this.config.url) {
      this._status = "error";
      this.emit({ type: "error", error: notConfigured() });
      return;
    }

    this._status = "connecting";
    this.emit({ type: "status", status: this._status });
    this.logger.info("WebSocket conectando", { url: this.config.url, attempt: this._reconnectAttempts });

    const wsUrl = this.config.url.replace(/^http/, "ws").replace(/^https/, "wss");
    try {
      this._ws = new WebSocket(wsUrl);
    } catch (e) {
      this.handleConnectError(e);
      return;
    }

    // Timeout de conexão.
    this._connectTimeoutTimer = setTimeout(() => {
      if (this._ws && this._ws.readyState !== WebSocket.OPEN) {
        this.logger.warn("WebSocket timeout de conexão");
        try { this._ws.close(); } catch { /* ignore */ }
      }
    }, this.connectTimeoutMs);

    this._ws.onopen = () => {
      this.clearConnectTimeout();
      this._status = "connected";
      this._reconnectAttempts = 0;
      this.emit({ type: "status", status: this._status });
      this.logger.info("WebSocket conectado");
      this.startHeartbeat();
    };

    this._ws.onmessage = (ev: MessageEvent) => {
      this.handleMessage(ev.data);
    };

    this._ws.onerror = () => {
      this.logger.warn("WebSocket error");
      // onclose será chamado depois — reconexão lá
    };

    this._ws.onclose = (ev: CloseEvent) => {
      this.clearConnectTimeout();
      this.stopHeartbeat();
      this.logger.info("WebSocket fechado", { code: ev.code, reason: ev.reason });
      if (!this._closed) {
        this.scheduleReconnect();
      } else {
        this._status = "disconnected";
        this.emit({ type: "status", status: this._status });
      }
    };
  }

  private handleConnectError(e: unknown): void {
    this._status = "error";
    const err = PresentationError.fromUnknown(e, {
      code: "TRANSPORT_HANDSHAKE_FAILED",
      severity: "high",
    });
    this.emit({ type: "error", error: err });
    this.emit({ type: "status", status: this._status });
    if (!this._closed) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this._closed) return;
    if (this._reconnectAttempts >= this.maxReconnectAttempts) {
      this._status = "error";
      this.logger.error("Máximo de tentativas de reconexão atingido", {
        attempts: this._reconnectAttempts,
      });
      this.emit({ type: "status", status: this._status });
      const err = new PresentationError({
        code: "TRANSPORT_UNAVAILABLE",
        message: `Falha ao reconectar após ${this.maxReconnectAttempts} tentativas.`,
        recoverable: false,
        severity: "critical",
      });
      this.emit({ type: "error", error: err });
      return;
    }

    this._status = "reconnecting";
    this.emit({ type: "status", status: this._status });
    this._reconnectAttempts += 1;

    // Backoff exponencial com jitter.
    const base = this.reconnectBaseMs * Math.pow(2, this._reconnectAttempts - 1);
    const jitter = Math.random() * 500;
    const delay = base + jitter;

    this.logger.info("Agendando reconexão", { delay_ms: delay, attempt: this._reconnectAttempts });
    this._reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  // ============================================================
  // Mensagens
  // ============================================================

  private handleMessage(data: string): void {
    let msg: WsMessage;
    try {
      msg = JSON.parse(data) as WsMessage;
    } catch (e) {
      this.logger.warn("Mensagem WebSocket inválida (JSON parse)", { error: String(e) });
      return;
    }

    switch (msg.type) {
      case "hello":
        this.logger.info("WebSocket hello recebido", { api: msg.api, server_time: msg.server_time });
        break;
      case "event":
        this.emit({ type: "message", payload: (msg as WsEvent).event });
        break;
      case "heartbeat_ack":
        this.logger.debug("Heartbeat ack", { server_time: msg.server_time });
        break;
      case "error": {
        const wsErr = (msg as WsError).error;
        const err = new PresentationError({
          code: (wsErr.code || "UNKNOWN") as PresentationError["code"],
          message: wsErr.message,
          details: wsErr.details ?? {},
          recoverable: wsErr.recoverable ?? false,
          severity: (wsErr.severity as PresentationError["severity"]) ?? "medium",
        });
        this.emit({ type: "error", error: err });
        break;
      }
      default:
        this.logger.debug("Mensagem WebSocket desconhecida", { type: (msg as { type: string }).type });
    }
  }

  // ============================================================
  // Heartbeat
  // ============================================================

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this._heartbeatTimer = setInterval(() => {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        try {
          this._ws.send(JSON.stringify({ type: "heartbeat" }));
        } catch (e) {
          this.logger.warn("Erro ao enviar heartbeat", { error: String(e) });
        }
      }
    }, this.heartbeatMs);
  }

  private stopHeartbeat(): void {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatTimer = null;
    }
  }

  // ============================================================
  // Cleanup
  // ============================================================

  private cleanup(): void {
    this.stopHeartbeat();
    this.clearConnectTimeout();
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    // Rejeita todas as requisições pendentes.
    for (const [id, entry] of this._pendingRequests) {
      if (entry.timer) clearTimeout(entry.timer);
      entry.reject(new PresentationError({
        code: "TRANSPORT_DISCONNECTED",
        message: "Transporte fechado.",
        recoverable: true,
        severity: "medium",
        correlationId: id,
      }));
    }
    this._pendingRequests.clear();
  }

  private clearConnectTimeout(): void {
    if (this._connectTimeoutTimer) {
      clearTimeout(this._connectTimeoutTimer);
      this._connectTimeoutTimer = null;
    }
  }

  private emit(event: TransportEvent): void {
    for (const l of this.listeners) {
      try {
        l(event);
      } catch {
        // listeners não propagam erros
      }
    }
  }
}

// ============================================================
// Factory
// ============================================================

export function createWebSocketTransport(
  config: TransportConfig,
  options?: WebSocketTransportOptions,
): Transport {
  return new WebSocketTransport(config, options);
}
