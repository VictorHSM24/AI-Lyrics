/**
 * EventStreamBridge — conecta Client SDK → EventStream → SnapshotStores.
 *
 * Responsabilidades:
 * - Assina eventos do Client SDK (ClientEvent do tipo "event")
 * - Converte para StreamEvent e publica no EventStream
 * - Assina o EventStream e atualiza os SnapshotStores apropriados
 *
 * NÃO executa lógica de negócio.
 * NÃO conhece React.
 * NÃO conhece transporte.
 *
 * Fluxo:
 *   Client SDK → (event) → Bridge → EventStream → Bridge → Stores
 */

import type { Client } from "@/sdk";
import {
  eventDtoToStreamEvent,
  type EventStream,
  type StreamEvent,
  type StreamSubscription,
} from "@/stream";
import { dispatchDomainHandlers } from "@/stream/handlers";
import type { StoreRegistry } from "@/stores";
import type { EventDTO } from "@/types";
import { devLog } from "@/utils";

// ============================================================
// EventStreamBridge
// ============================================================

export class EventStreamBridge {
  private readonly client: Client;
  private readonly stream: EventStream;
  private readonly stores: StoreRegistry;
  private clientSub: (() => void) | null = null;
  private streamSub: StreamSubscription | null = null;
  private started = false;

  constructor(client: Client, stream: EventStream, stores: StoreRegistry) {
    this.client = client;
    this.stream = stream;
    this.stores = stores;
  }

  /** Inicia a ponte — assina Client SDK e EventStream. */
  start(): void {
    if (this.started) return;
    this.started = true;
    devLog.bridge("Bridge iniciada — assinando Client SDK e EventStream");

    // 1. Assina eventos do Client SDK → publica no EventStream.
    this.clientSub = this.client.subscribe((event) => {
      if (event.type === "event") {
        this.handleClientEvent(event.payload);
      }
    });

    // 2. Assina o EventStream → atualiza Stores.
    this.streamSub = this.stream.subscribe((streamEvent) => {
      this.handleStreamEvent(streamEvent);
    });
  }

  /** Para a ponte. */
  stop(): void {
    this.started = false;
    if (this.clientSub) {
      this.clientSub();
      this.clientSub = null;
    }
    if (this.streamSub) {
      this.streamSub.unsubscribe();
      this.streamSub = null;
    }
  }

  // ============================================================
  // Client SDK → EventStream
  // ============================================================

  private handleClientEvent(payload: unknown): void {
    // O payload é um EventDTO recebido via WebSocket.
    const dto = payload as EventDTO;
    if (!dto || typeof dto !== "object" || !("event_type" in dto)) {
      // Payload não é um EventDTO — ignora.
      return;
    }
    const streamEvent = eventDtoToStreamEvent(dto);
    this.stream.publish(streamEvent);
  }

  // ============================================================
  // EventStream → Stores
  // ============================================================

  private handleStreamEvent(event: StreamEvent): void {
    const dto = event.payload as EventDTO;
    console.log("[DIAG bridge] handleStreamEvent:", dto?.event_type);
    if (!dto || typeof dto !== "object" || !("event_type" in dto)) {
      return;
    }

    // Atualiza o EventStore (histórico de eventos).
    const currentEvents = this.stores.events.current?.data ?? [];
    this.stores.events.set([...currentEvents, dto]);

    // Despacha para handlers de domínio organizados.
    // Cada handler atualiza apenas os Stores correspondentes.
    dispatchDomainHandlers(dto, this.stores);
  }
}

// ============================================================
// Factory
// ============================================================

export function createEventStreamBridge(
  client: Client,
  stream: EventStream,
  stores: StoreRegistry,
): EventStreamBridge {
  return new EventStreamBridge(client, stream, stores);
}
