/**
 * REST Transport — implementação real de Transport via fetch().
 *
 * Usa a Fetch API nativa do browser. Sem dependências externas.
 *
 * Recursos:
 * - Serialização JSON
 * - Timeout via AbortController
 * - Cancelamento via CancelToken
 * - Versionamento automático (espera Versioned<T>)
 * - Tratamento de erros → PresentationError
 * - Headers configuráveis
 *
 * NÃO implementa cache, retry nem heartbeat (essas responsabilidades
 * pertencem ao Client SDK, não ao Transport).
 */

import { canceled, notConfigured, PresentationError, timeout as timeoutError } from "../errors";
import type { CancelToken } from "../cancel";
import type {
  Transport,
  TransportConfig,
  TransportEvent,
  TransportListener,
  TransportRequest,
  TransportResult,
  TransportStatus,
} from "../transport";
import type { Versioned } from "../versioning";

// ============================================================
// Logger — logging estruturado de infraestrutura.
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
// Mapeamento de métodos SDK → endpoints REST.
// ============================================================

const METHOD_TO_ENDPOINT: Record<string, string> = {
  "pipeline.getStatus": "/pipeline/status",
  "pipeline.getSession": "/pipeline/session",
  "pipeline.getMetrics": "/pipeline/metrics",
  "pipeline.getSnapshot": "/pipeline/snapshot",
  "pipeline.start": "/pipeline/start",
  "pipeline.stop": "/pipeline/stop",
  "session.getCurrent": "/session/current",
  "metrics.get": "/metrics",
  "configuration.get": "/configuration",
  "configuration.update": "/configuration",
  "health.get": "/health",
  "health.testHolyrics": "/health/holyrics/test",
  "diagnostics.get": "/diagnostics",
  "events.getAll": "/events",
  "events.getByCorrelation": "/events/by-correlation",
  "events.getBySession": "/events/by-session",
  "events.getSnapshot": "/events/snapshot",
  "replay.getEvents": "/replay/events",
  "replay.getSessions": "/replay/sessions",
  "replay.getCorrelations": "/replay/correlations",
  "audio.getDevices": "/audio/devices",
  "audio.getCurrent": "/audio/current",
  "audio.getLevels": "/audio/levels",
  "audio.start": "/audio/start",
  "audio.stop": "/audio/stop",
  "audio.select": "/audio/select",
  "system.get": "/system",
  "info.get": "/info",
};

/** Métodos que usam PUT (body JSON) em vez de GET (query params). */
const PUT_METHODS: ReadonlySet<string> = new Set([
  "configuration.update",
]);

/** Métodos que usam POST (body JSON) em vez de GET (query params). */
const POST_METHODS: ReadonlySet<string> = new Set([
  "audio.start",
  "audio.stop",
  "audio.select",
  "health.testHolyrics",
  "pipeline.start",
  "pipeline.stop",
]);

// ============================================================
// RestTransport
// ============================================================

export interface RestTransportOptions {
  logger?: Logger;
}

export class RestTransport implements Transport {
  private readonly config: TransportConfig;
  private readonly logger: Logger;
  private readonly listeners: TransportListener[] = [];
  private _status: TransportStatus = "idle";

  constructor(config: TransportConfig, options: RestTransportOptions = {}) {
    this.config = config;
    this.logger = options.logger ?? noopLogger;
  }

  get status(): TransportStatus {
    return this._status;
  }

  async open(): Promise<void> {
    // REST não tem conexão persistente — apenas marca como conectado.
    this._status = "connected";
    this.emit({ type: "status", status: this._status });
    this.logger.info("REST transport aberto", { url: this.config.url });
  }

  async close(): Promise<void> {
    this._status = "disconnected";
    this.emit({ type: "status", status: this._status });
    this.logger.info("REST transport fechado");
  }

  subscribe(listener: TransportListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  async request<T>(req: TransportRequest): Promise<TransportResult<T>> {
    const endpoint = METHOD_TO_ENDPOINT[req.method];
    if (!endpoint) {
      const err = new PresentationError({
        code: "SERVICE_NOT_FOUND",
        message: `Método desconhecido: ${req.method}`,
        recoverable: false,
        severity: "low",
        details: { method: req.method },
      });
      this.emit({ type: "error", error: err });
      return { id: req.id, ok: false, error: err };
    }

    if (!this.config.url) {
      const err = notConfigured();
      return { id: req.id, ok: false, error: err };
    }

    const url = this.buildUrl(endpoint, (PUT_METHODS.has(req.method) || POST_METHODS.has(req.method)) ? {} : req.params);
    const timeoutMs = req.timeoutMs ?? this.config.defaultTimeoutMs ?? 30000;
    const cancel = req.cancel;

    // AbortController para timeout + cancelamento.
    const controller = new AbortController();
    const timer = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;

    // Hook de cancelamento.
    let cancelDispose: (() => void) | null = null;
    if (cancel) {
      cancelDispose = cancel.onCancel(() => controller.abort());
      if (cancel.canceled) {
        controller.abort();
      }
    }

    try {
      this.logger.debug("REST request", { method: req.method, url });
      const isPut = PUT_METHODS.has(req.method);
      const isPost = POST_METHODS.has(req.method);
      const hasBody = isPut || isPost;
      const headers: Record<string, string> = {
        "Accept": "application/json",
        ...(this.config.headers ?? {}),
      };

      const fetchOptions: RequestInit = {
        method: isPut ? "PUT" : isPost ? "POST" : "GET",
        headers,
        signal: controller.signal,
      };
      if (hasBody) {
        headers["Content-Type"] = "application/json";
        fetchOptions.body = JSON.stringify(req.params);
      }

      const response = await fetch(url, fetchOptions);

      if (!response.ok) {
        const err = await this.parseError(response, req.id);
        this.emit({ type: "error", error: err });
        return { id: req.id, ok: false, error: err };
      }

      const json = await response.json() as Versioned<T>;
      return { id: req.id, ok: true, result: json };
    } catch (e) {
      const err = this.handleError(e, req.id, timeoutMs, cancel);
      this.emit({ type: "error", error: err });
      return { id: req.id, ok: false, error: err };
    } finally {
      if (timer) clearTimeout(timer);
      if (cancelDispose) cancelDispose();
    }
  }

  private buildUrl(endpoint: string, params: Record<string, unknown>): string {
    const base = this.config.url.replace(/\/$/, "");
    let url = `${base}${endpoint}`;
    // Query params para filtros.
    const query: string[] = [];
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      query.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
    }
    if (query.length > 0) {
      url += `?${query.join("&")}`;
    }
    return url;
  }

  private async parseError(response: Response, reqId: string): Promise<PresentationError> {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // resposta não-JSON
    }
    const code = (body as { code?: string })?.code ?? "SERVICE_UNAVAILABLE";
    const message = (body as { message?: string })?.message ?? `HTTP ${response.status}`;
    return new PresentationError({
      code: code as PresentationError["code"],
      message,
      recoverable: response.status >= 500,
      severity: response.status >= 500 ? "high" : "medium",
      details: { status: response.status, url: response.url },
      correlationId: reqId,
    });
  }

  private handleError(
    e: unknown,
    reqId: string,
    timeoutMs: number,
    cancel?: CancelToken,
  ): PresentationError {
    if (e instanceof DOMException && e.name === "AbortError") {
      if (cancel?.canceled) {
        return canceled(reqId);
      }
      return timeoutError(timeoutMs, reqId);
    }
    if (e instanceof PresentationError) return e;
    return PresentationError.fromUnknown(e, { correlationId: reqId });
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

export function createRestTransport(
  config: TransportConfig,
  options?: RestTransportOptions,
): Transport {
  return new RestTransport(config, options);
}
