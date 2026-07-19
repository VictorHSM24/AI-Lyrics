import { describe, it, expect } from "vitest";
import {
  createEventStream,
  eventDtoToStreamEvent,
  EventStreamImpl,
  type StreamEvent,
} from "@/stream";
import type { EventDTO } from "@/types";

function makeEvent(type: string, corrId: string | null = null): StreamEvent {
  return {
    id: `e-${type}`,
    type,
    timestamp: Date.now() / 1000,
    correlationId: corrId,
    payload: { event_type: type, meta: { correlation_id: corrId }, payload: {} },
  };
}

function makeEventDTO(type: string, corrId: string = "c1"): EventDTO {
  return {
    event_type: type,
    meta: {
      event_id: "e1",
      correlation_id: corrId,
      causation_id: null,
      session_id: "s1",
      timestamp: 100.0,
      origin: "test",
      metadata: [],
    },
    payload: {},
  };
}

describe("EventStream", () => {
  it("createEventStream retorna EventStream", () => {
    const s = createEventStream();
    expect(s).toBeDefined();
    expect(typeof s.publish).toBe("function");
    expect(typeof s.subscribe).toBe("function");
    expect(typeof s.snapshot).toBe("function");
    expect(typeof s.history).toBe("function");
    expect(typeof s.clear).toBe("function");
    expect(typeof s.close).toBe("function");
    expect(s.closed).toBe(false);
  });

  it("EventStreamImpl pode ser instanciado diretamente", () => {
    const s = new EventStreamImpl();
    expect(s).toBeDefined();
    expect(s.closed).toBe(false);
  });

  it("publish distribui para subscribers globais", () => {
    const s = createEventStream();
    let received: StreamEvent | null = null;
    s.subscribe((e) => {
      received = e;
    });
    const ev = makeEvent("TestEvent");
    s.publish(ev);
    expect(received).toBe(ev);
  });

  it("subscribe retorna subscription com unsubscribe", () => {
    const s = createEventStream();
    let count = 0;
    const sub = s.subscribe(() => {
      count++;
    });
    s.publish(makeEvent("A"));
    expect(count).toBe(1);
    sub.unsubscribe();
    s.publish(makeEvent("B"));
    expect(count).toBe(1);
  });

  it("subscribeToType filtra por tipo", () => {
    const s = createEventStream();
    let typeA: StreamEvent[] = [];
    let typeB: StreamEvent[] = [];
    s.subscribeToType("A", (e) => typeA.push(e));
    s.subscribeToType("B", (e) => typeB.push(e));
    s.publish(makeEvent("A"));
    s.publish(makeEvent("B"));
    s.publish(makeEvent("A"));
    expect(typeA).toHaveLength(2);
    expect(typeB).toHaveLength(1);
  });

  it("subscribeToCorrelation filtra por correlação", () => {
    const s = createEventStream();
    let corr1: StreamEvent[] = [];
    s.subscribeToCorrelation("c1", (e) => corr1.push(e));
    s.publish(makeEvent("A", "c1"));
    s.publish(makeEvent("B", "c2"));
    s.publish(makeEvent("C", "c1"));
    expect(corr1).toHaveLength(2);
    expect(corr1[0].type).toBe("A");
    expect(corr1[1].type).toBe("C");
  });

  it("snapshot retorna estado atual", () => {
    const s = createEventStream();
    s.publish(makeEvent("A"));
    s.publish(makeEvent("B"));
    const snap = s.snapshot();
    expect(snap.eventCount).toBe(2);
    expect(snap.lastEvent).not.toBeNull();
    expect(snap.lastEvent!.type).toBe("B");
    expect(snap.lastEventAt).toBeGreaterThan(0);
    expect(snap.types).toContain("A");
    expect(snap.types).toContain("B");
  });

  it("snapshot vazio quando stream está limpo", () => {
    const s = createEventStream();
    const snap = s.snapshot();
    expect(snap.eventCount).toBe(0);
    expect(snap.lastEvent).toBeNull();
    expect(snap.lastEventAt).toBe(0);
    expect(snap.types).toEqual([]);
  });

  it("history retorna eventos", () => {
    const s = createEventStream();
    s.publish(makeEvent("A"));
    s.publish(makeEvent("B"));
    s.publish(makeEvent("C"));
    const h = s.history();
    expect(h).toHaveLength(3);
    expect(h[0].type).toBe("A");
    expect(h[2].type).toBe("C");
  });

  it("history com limit retorna últimos N", () => {
    const s = createEventStream();
    s.publish(makeEvent("A"));
    s.publish(makeEvent("B"));
    s.publish(makeEvent("C"));
    const h = s.history(2);
    expect(h).toHaveLength(2);
    expect(h[0].type).toBe("B");
    expect(h[1].type).toBe("C");
  });

  it("clear limpa o stream", () => {
    const s = createEventStream();
    s.publish(makeEvent("A"));
    s.publish(makeEvent("B"));
    s.clear();
    expect(s.snapshot().eventCount).toBe(0);
    expect(s.snapshot().lastEvent).toBeNull();
    expect(s.snapshot().types).toEqual([]);
  });

  it("close fecha o stream", () => {
    const s = createEventStream();
    s.close();
    expect(s.closed).toBe(true);
  });

  it("publish em stream fechado lança erro", () => {
    const s = createEventStream();
    s.close();
    expect(() => s.publish(makeEvent("A"))).toThrow();
  });

  it("subscribe em stream fechado lança erro", () => {
    const s = createEventStream();
    s.close();
    expect(() => s.subscribe(() => {})).toThrow();
  });

  it("history limit respeita limite configurado", () => {
    const s = new EventStreamImpl(3);
    s.publish(makeEvent("A"));
    s.publish(makeEvent("B"));
    s.publish(makeEvent("C"));
    s.publish(makeEvent("D"));
    const h = s.history();
    expect(h).toHaveLength(3);
    expect(h[0].type).toBe("B");
    expect(h[2].type).toBe("D");
  });

  it("listener que lança não propaga erro", () => {
    const s = createEventStream();
    s.subscribe(() => {
      throw new Error("listener error");
    });
    let otherReceived = false;
    s.subscribe(() => {
      otherReceived = true;
    });
    expect(() => s.publish(makeEvent("A"))).not.toThrow();
    expect(otherReceived).toBe(true);
  });
});

describe("eventDtoToStreamEvent", () => {
  it("converte EventDTO para StreamEvent", () => {
    const dto = makeEventDTO("TestEvent", "c1");
    const ev = eventDtoToStreamEvent(dto);
    expect(ev.type).toBe("TestEvent");
    expect(ev.correlationId).toBe("c1");
    expect(ev.timestamp).toBe(100.0);
    expect(ev.payload).toBe(dto);
    expect(ev.id).toMatch(/^stream-\d+$/);
  });

  it("gera IDs únicos", () => {
    const dto = makeEventDTO("A");
    const e1 = eventDtoToStreamEvent(dto);
    const e2 = eventDtoToStreamEvent(dto);
    expect(e1.id).not.toBe(e2.id);
  });
});
