/**
 * Error Model — modelo único de erros da interface web.
 *
 * Todos os Services, Client SDK e EventStream deverão utilizar
 * exclusivamente este contrato para reportar erros.
 *
 * Nenhum erro "cru" (Error, TypeError, etc.) deve propagar-se
 * além das fronteiras das camadas de infraestrutura.
 */

import type { EventMetadataDTO } from "@/types";

// ============================================================
// Severity
// ============================================================

export type ErrorSeverity = "info" | "low" | "medium" | "high" | "critical";

export const ERROR_SEVERITIES: readonly ErrorSeverity[] = [
  "info",
  "low",
  "medium",
  "high",
  "critical",
] as const;

// ============================================================
// Error codes — namespace por domínio.
// ============================================================

export type ErrorCode =
  // Transporte
  | "TRANSPORT_TIMEOUT"
  | "TRANSPORT_DISCONNECTED"
  | "TRANSPORT_RECONNECTING"
  | "TRANSPORT_HANDSHAKE_FAILED"
  | "TRANSPORT_AUTH_REQUIRED"
  | "TRANSPORT_RATE_LIMITED"
  | "TRANSPORT_UNAVAILABLE"
  // SDK
  | "SDK_NOT_CONFIGURED"
  | "SDK_SERIALIZATION_FAILED"
  | "SDK_DESERIALIZATION_FAILED"
  | "SDK_VERSION_MISMATCH"
  | "SDK_CANCELED"
  // Services
  | "SERVICE_NOT_FOUND"
  | "SERVICE_UNAVAILABLE"
  | "SERVICE_INVALID_ARGUMENT"
  // EventStream
  | "STREAM_OVERFLOW"
  | "STREAM_CLOSED"
  | "STREAM_SUBSCRIPTION_FAILED"
  // SnapshotStore
  | "STORE_EMPTY"
  | "STORE_STALE"
  | "STORE_CONFLICT"
  // Genérico
  | "UNKNOWN";

// ============================================================
// PresentationError
// ============================================================

export interface PresentationErrorLike {
  readonly code: ErrorCode;
  readonly message: string;
  readonly details: Record<string, unknown>;
  readonly recoverable: boolean;
  readonly severity: ErrorSeverity;
  readonly correlationId: string | null;
  readonly timestamp: number;
  readonly cause?: PresentationErrorLike | null;
}

/**
 * Erro canônico da Presentation Layer do frontend.
 *
 * Convenções:
 * - `recoverable=true` → a interface pode tentar novamente.
 * - `recoverable=false` → ação humana é necessária.
 * - `severity=critical` → toda a interface deve parar.
 * - `severity=info` → apenas log, sem impacto visual.
 */
export class PresentationError extends Error {
  readonly code: ErrorCode;
  readonly details: Record<string, unknown>;
  readonly recoverable: boolean;
  readonly severity: ErrorSeverity;
  readonly correlationId: string | null;
  readonly timestamp: number;
  readonly cause: PresentationError | null;

  constructor(params: {
    code: ErrorCode;
    message: string;
    details?: Record<string, unknown>;
    recoverable?: boolean;
    severity?: ErrorSeverity;
    correlationId?: string | null;
    timestamp?: number;
    cause?: PresentationError | null;
  }) {
    super(params.message);
    this.name = "PresentationError";
    this.code = params.code;
    this.details = params.details ?? {};
    this.recoverable = params.recoverable ?? false;
    this.severity = params.severity ?? "medium";
    this.correlationId = params.correlationId ?? null;
    this.timestamp = params.timestamp ?? Date.now() / 1000;
    this.cause = params.cause ?? null;
    // Mantém stack trace em V8.
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, PresentationError);
    }
  }

  toDTO(): PresentationErrorLike {
    return {
      code: this.code,
      message: this.message,
      details: this.details,
      recoverable: this.recoverable,
      severity: this.severity,
      correlationId: this.correlationId,
      timestamp: this.timestamp,
      cause: this.cause?.toDTO() ?? null,
    };
  }

  /**
   * Cria um PresentationError a partir de um erro genérico,
   * preservando a mensagem original.
   */
  static fromUnknown(
    err: unknown,
    overrides: Partial<ConstructorParameters<typeof PresentationError>[0]> = {},
  ): PresentationError {
    if (err instanceof PresentationError) {
      return err;
    }
    const message =
      err instanceof Error ? err.message : String(err ?? "Erro desconhecido");
    return new PresentationError({
      code: "UNKNOWN",
      message,
      ...overrides,
    });
  }

  /**
   * Cria um PresentationError a partir de metadados de evento,
   * útil quando o erro está correlacionado a um evento.
   */
  static fromEvent(
    meta: EventMetadataDTO,
    overrides: Partial<Omit<ConstructorParameters<typeof PresentationError>[0], "code" | "message">> & {
      code?: ErrorCode;
      message?: string;
    } = {},
  ): PresentationError {
    return new PresentationError({
      code: overrides.code ?? "UNKNOWN",
      message: overrides.message ?? "Erro correlacionado a evento",
      correlationId: meta.correlation_id,
      timestamp: meta.timestamp,
      details: overrides.details,
      recoverable: overrides.recoverable,
      severity: overrides.severity,
      cause: overrides.cause,
    });
  }
}

// ============================================================
// Result — alternativa a throw para fluxos controlados.
// ============================================================

export type Result<T, E = PresentationError> =
  | { ok: true; value: T }
  | { ok: false; error: E };

export function ok<T>(value: T): Result<T, never> {
  return { ok: true, value };
}

export function err<E extends PresentationError>(error: E): Result<never, E> {
  return { ok: false, error };
}

/**
 * Verifica se um Result é sucesso.
 */
export function isOk<T, E>(r: Result<T, E>): r is { ok: true; value: T } {
  return r.ok;
}

/**
 * Verifica se um Result é erro.
 */
export function isErr<T, E>(r: Result<T, E>): r is { ok: false; error: E } {
  return !r.ok;
}

// ============================================================
// Helpers para códigos comuns.
// ============================================================

export function canceled(correlationId?: string | null): PresentationError {
  return new PresentationError({
    code: "SDK_CANCELED",
    message: "Operação cancelada.",
    recoverable: true,
    severity: "info",
    correlationId: correlationId ?? null,
  });
}

export function timeout(ms: number, correlationId?: string | null): PresentationError {
  return new PresentationError({
    code: "TRANSPORT_TIMEOUT",
    message: `Tempo limite excedido (${ms}ms).`,
    recoverable: true,
    severity: "medium",
    correlationId: correlationId ?? null,
    details: { timeout_ms: ms },
  });
}

export function notConfigured(): PresentationError {
  return new PresentationError({
    code: "SDK_NOT_CONFIGURED",
    message: "Client SDK não configurado — backend ainda não disponível.",
    recoverable: false,
    severity: "low",
  });
}
