/**
 * Cancelamento — infraestrutura para cancelar operações assíncronas.
 *
 * Toda chamada futura do Client SDK, Services e EventStream deverá
 * aceitar um CancelToken opcional. Nenhuma implementação real de
 * cancelamento é feita aqui — apenas os contratos.
 */

import { canceled } from "./errors";

// ============================================================
// CancelToken
// ============================================================

export interface CancelToken {
  /** True se o token foi cancelado. */
  readonly canceled: boolean;
  /** Razão do cancelamento (opcional). */
  readonly reason: string | null;
  /** Registra callback executado no cancelamento. Retorna função de dispose. */
  onCancel(callback: (reason: string | null) => void): () => void;
  /** Lança PresentationError se cancelado. */
  throwIfCanceled(): void;
}

// ============================================================
// CancelSource — fonte de um CancelToken.
// ============================================================

export interface CancelSource {
  readonly token: CancelToken;
  cancel(reason?: string): void;
}

// ============================================================
// Implementação — CancelToken concreto.
// ============================================================

class CancelTokenImpl implements CancelToken {
  private _canceled = false;
  private _reason: string | null = null;
  private _callbacks: Array<(reason: string | null) => void> = [];

  get canceled(): boolean {
    return this._canceled;
  }

  get reason(): string | null {
    return this._reason;
  }

  onCancel(callback: (reason: string | null) => void): () => void {
    if (this._canceled) {
      callback(this._reason);
      return () => {};
    }
    this._callbacks.push(callback);
    return () => {
      const idx = this._callbacks.indexOf(callback);
      if (idx >= 0) this._callbacks.splice(idx, 1);
    };
  }

  throwIfCanceled(): void {
    if (this._canceled) {
      throw canceled(this._reason);
    }
  }

  _cancel(reason?: string): void {
    if (this._canceled) return;
    this._canceled = true;
    this._reason = reason ?? null;
    for (const cb of this._callbacks) {
      try {
        cb(this._reason);
      } catch {
        // Callbacks de cancelamento não devem propagar erros.
      }
    }
    this._callbacks = [];
  }
}

/**
 * Cria uma nova fonte de cancelamento.
 */
export function createCancelSource(): CancelSource {
  const impl = new CancelTokenImpl();
  return {
    token: impl,
    cancel: (reason?: string) => impl._cancel(reason),
  };
}

/**
 * Token que nunca é cancelado.
 */
export const NEVER_CANCEL: CancelToken = {
  get canceled() {
    return false;
  },
  get reason() {
    return null;
  },
  onCancel() {
    return () => {};
  },
  throwIfCanceled() {
    /* noop */
  },
};

/**
 * Cria um token já cancelado.
 */
export function canceledToken(reason?: string): CancelToken {
  const src = createCancelSource();
  src.cancel(reason);
  return src.token;
}

/**
 * Combina múltiplos tokens — cancela quando qualquer um cancelar.
 */
export function raceCancel(...tokens: CancelToken[]): CancelToken {
  const source = createCancelSource();
  for (const t of tokens) {
    t.onCancel((r) => source.cancel(r ?? undefined));
    if (t.canceled) {
      source.cancel(t.reason ?? undefined);
      break;
    }
  }
  return source.token;
}
