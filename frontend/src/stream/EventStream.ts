/**
 * EventStream — barramento de eventos do frontend.
 *
 * Responsabilidades:
 * - Receber eventos do Client SDK
 * - Registrar subscribers
 * - Unsubscribe
 * - Publicar eventos
 * - Armazenar último evento
 * - Histórico recente
 * - Snapshot do stream
 *
 * NÃO interpreta eventos.
 * NÃO executa lógica de negócio.
 * NÃO conhece React.
 * NÃO conhece transporte.
 */

import type { EventDTO } from "@/types";

// ============================================================
// StreamEvent — evento que flui pelo EventStream.
// ============================================================

export interface StreamEvent {
  readonly id: string;
  readonly type: string;
  readonly timestamp: number;
  readonly correlationId: string | null;
  readonly payload: EventDTO | unknown;
}

// ============================================================
// StreamSnapshot — snapshot imutável do estado do stream.
// ============================================================

export interface StreamSnapshot {
  readonly eventCount: number;
  readonly lastEvent: StreamEvent | null;
  readonly lastEventAt: number;
  readonly types: readonly string[];
}

// ============================================================
// StreamSubscription
// ============================================================

export interface StreamSubscription {
  unsubscribe(): void;
}

export interface StreamListener {
  (event: StreamEvent): void;
}

// ============================================================
// EventStream — contrato.
// ============================================================

export interface EventStream {
  /** Publica um evento no stream. */
  publish(event: StreamEvent): void;
  /** Inscreve um listener para todos os eventos. */
  subscribe(listener: StreamListener): StreamSubscription;
  /** Inscreve um listener para eventos de um tipo específico. */
  subscribeToType(type: string, listener: StreamListener): StreamSubscription;
  /** Inscreve um listener para eventos de uma correlação. */
  subscribeToCorrelation(correlationId: string, listener: StreamListener): StreamSubscription;
  /** Snapshot imutável do estado atual. */
  snapshot(): StreamSnapshot;
  /** Histórico recente (cópia imutável). */
  history(limit?: number): readonly StreamEvent[];
  /** Limpa o stream. */
  clear(): void;
  /** Fecha o stream permanentemente. */
  close(): void;
  /** True se o stream está fechado. */
  readonly closed: boolean;
}

// ============================================================
// EventStreamImpl
// ============================================================

import { PresentationError } from "@/sdk/errors";

const DEFAULT_HISTORY_LIMIT = 1000;

export class EventStreamImpl implements EventStream {
  private readonly listeners: Set<StreamListener> = new Set();
  private readonly typeListeners: Map<string, Set<StreamListener>> = new Map();
  private readonly corrListeners: Map<string, Set<StreamListener>> = new Map();
  private readonly events: StreamEvent[] = [];
  private readonly historyLimit: number;
  private _closed = false;
  private _lastEvent: StreamEvent | null = null;
  private readonly _types: Set<string> = new Set();

  constructor(historyLimit: number = DEFAULT_HISTORY_LIMIT) {
    this.historyLimit = historyLimit;
  }

  get closed(): boolean {
    return this._closed;
  }

  publish(event: StreamEvent): void {
    this.assertOpen();
    this._lastEvent = event;
    this._types.add(event.type);
    this.events.push(event);
    if (this.events.length > this.historyLimit) {
      this.events.splice(0, this.events.length - this.historyLimit);
    }
    // Notifica listeners globais.
    for (const l of this.listeners) {
      this.safeDispatch(l, event);
    }
    // Notifica listeners por tipo.
    const typeSet = this.typeListeners.get(event.type);
    if (typeSet) {
      for (const l of typeSet) {
        this.safeDispatch(l, event);
      }
    }
    // Notifica listeners por correlação.
    if (event.correlationId) {
      const corrSet = this.corrListeners.get(event.correlationId);
      if (corrSet) {
        for (const l of corrSet) {
          this.safeDispatch(l, event);
        }
      }
    }
  }

  subscribe(listener: StreamListener): StreamSubscription {
    this.assertOpen();
    this.listeners.add(listener);
    return { unsubscribe: () => this.listeners.delete(listener) };
  }

  subscribeToType(type: string, listener: StreamListener): StreamSubscription {
    this.assertOpen();
    let set = this.typeListeners.get(type);
    if (!set) {
      set = new Set();
      this.typeListeners.set(type, set);
    }
    set.add(listener);
    return { unsubscribe: () => set!.delete(listener) };
  }

  subscribeToCorrelation(correlationId: string, listener: StreamListener): StreamSubscription {
    this.assertOpen();
    let set = this.corrListeners.get(correlationId);
    if (!set) {
      set = new Set();
      this.corrListeners.set(correlationId, set);
    }
    set.add(listener);
    return { unsubscribe: () => set!.delete(listener) };
  }

  snapshot(): StreamSnapshot {
    return {
      eventCount: this.events.length,
      lastEvent: this._lastEvent,
      lastEventAt: this._lastEvent?.timestamp ?? 0,
      types: Array.from(this._types),
    };
  }

  history(limit?: number): readonly StreamEvent[] {
    if (limit === undefined || limit >= this.events.length) {
      return Array.from(this.events);
    }
    return this.events.slice(this.events.length - limit);
  }

  clear(): void {
    this.events.length = 0;
    this._lastEvent = null;
    this._types.clear();
  }

  close(): void {
    this._closed = true;
    this.listeners.clear();
    this.typeListeners.clear();
    this.corrListeners.clear();
  }

  private assertOpen(): void {
    if (this._closed) {
      throw new PresentationError({
        code: "STREAM_CLOSED",
        message: "EventStream está fechado.",
        recoverable: false,
        severity: "high",
      });
    }
  }

  private safeDispatch(listener: StreamListener, event: StreamEvent): void {
    try {
      listener(event);
    } catch {
      // Listeners não devem propagar erros para o stream.
    }
  }
}

// ============================================================
// Factory
// ============================================================

export function createEventStream(historyLimit?: number): EventStream {
  return new EventStreamImpl(historyLimit);
}

// ============================================================
// Helpers — conversão de EventDTO para StreamEvent.
// ============================================================

let _streamEventIdCounter = 0;

export function eventDtoToStreamEvent(dto: EventDTO): StreamEvent {
  _streamEventIdCounter += 1;
  return {
    id: `stream-${_streamEventIdCounter}`,
    type: dto.event_type,
    timestamp: dto.meta.timestamp,
    correlationId: dto.meta.correlation_id,
    payload: dto,
  };
}
